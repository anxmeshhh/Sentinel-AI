"""Investigate This: turn one attention item into an evidence-backed account
of what happened, why it matters, and what to consider doing next.

## Why this is not RAG over everything connected

The temptation with a feature named "investigate" is to hand a model the
whole workspace and ask it to think. That is expensive, slow, and - in a
product whose entire premise is authorization boundaries - unsafe, because a
retriever that ranks by similarity has no idea which mailbox it is allowed
to read.

So retrieval here is deterministic and correlation-driven, following the
same pattern as meeting_prep: find the anchor, follow four *specific*
relationships outward, rank, cap, and spend exactly one LLM call to
synthesize what was found.

    anchor signal        the item's own source, already in the database
    same thread          the conversation it belongs to
    same correspondent   what else that person/system has been sending
    shared keywords      other items about the same subject
    temporal neighbours  what else happened around it, across providers

The last one is what makes this more than "Ask Sentinel about this email":
it crosses providers. A failed deployment correlates with the commits and
meetings around it, not just with other emails.

## Facts and inference are kept apart

`evidence` is retrieved from Signals, carries links, and the model never
writes it. The narrative fields are the model's reading *of* that evidence
and are labelled as inference in the UI. A user who distrusts the narrative
can check every fact it was built from.

## Authorization is the retrieval scope

There is one connection set per investigation, decided before any retrieval
runs, and every query is filtered to it:

    personal   the viewer's own connections in this workspace
    channel    exactly what that channel is authorized for (the Phase 2
               resolver: workspace u class u group u channel - exclusions)

This is why a channel investigation cannot pull in the investigator's private
mail: the private connection is not in the set, so no query can reach it.
The boundary is the query filter, not a post-hoc check on the results.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.llm import LLMClient, LLMError
from app.models.attention_item import AttentionItem, AttentionOrigin
from app.models.connection import Connection
from app.models.investigation import Investigation
from app.models.signal import Signal, SignalType
from app.services.channel_authorization import resolve_channel_scope
from app.services.mail_signals import noise_reason, sender_counts
from app.services.meeting_prep import meaningful_keywords

logger = structlog.get_logger("sentinel.investigation")

# How far around the anchor to look for related activity. Wide enough that a
# deploy and the meeting about it land in the same window, narrow enough that
# a month of unrelated mail does not.
NEIGHBOUR_WINDOW = timedelta(hours=72)
CORRESPONDENT_WINDOW = timedelta(days=14)

# Hard cap on what reaches the model. Evidence is ranked, so the cap drops
# the weakest relationships rather than truncating arbitrarily. This is the
# single biggest control on token cost and latency.
MAX_EVIDENCE = 12

_RELATION_RANK = {
    "same_thread": 0,
    "same_correspondent": 1,
    "shared_subject": 2,
    "around_the_same_time": 3,
}

_RELATION_LABEL = {
    "same_thread": "In the same conversation",
    "same_correspondent": "From the same sender",
    "shared_subject": "About the same subject",
    "around_the_same_time": "Happened around the same time",
}


class InvestigationError(Exception):
    pass


class NotAuthorized(InvestigationError):
    pass


@dataclass
class Scope:
    """The connection set an investigation may read, decided up front."""

    key: str  # "personal:{user_id}" | "channel:{team_id}"
    connection_ids: set[uuid.UUID] = field(default_factory=set)


def personal_scope(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Scope:
    connection_ids = set(session.execute(
        select(Connection.id).where(Connection.workspace_id == workspace_id, Connection.user_id == user_id)
    ).scalars())
    return Scope(key=f"personal:{user_id}", connection_ids=connection_ids)


def channel_scope(session: Session, team_id: uuid.UUID) -> Scope:
    resolved = resolve_channel_scope(session, team_id)
    return Scope(key=f"channel:{team_id}", connection_ids=set(resolved["connections"]))


def investigate(
    session: Session,
    *,
    item: AttentionItem,
    scope: Scope,
    refresh: bool = False,
) -> Investigation:
    """Investigate one attention item within one authorization scope.

    Raises NotAuthorized if the item's own source is not in the scope - which
    is the same check that decides whether the item should have been visible
    at all, applied again here rather than trusted from the caller.
    """
    _assert_in_scope(item, scope)

    if not refresh:
        cached = session.execute(
            select(Investigation).where(
                Investigation.attention_item_id == item.id, Investigation.scope_key == scope.key
            )
        ).scalar_one_or_none()
        if cached is not None:
            return cached

    anchor = _anchor_signal(session, item, scope)
    evidence = _gather_evidence(session, item, anchor, scope)

    if evidence:
        narrative, llm_calls = _synthesize(item, anchor, evidence)
    else:
        # Nothing correlated. There is nothing for a model to reason across,
        # so it isn't asked - the same discipline meeting_prep uses. The user
        # still gets an honest answer instead of an invented one.
        narrative, llm_calls = _no_evidence_narrative(item), 0

    investigation = session.execute(
        select(Investigation).where(
            Investigation.attention_item_id == item.id, Investigation.scope_key == scope.key
        )
    ).scalar_one_or_none()
    if investigation is None:
        investigation = Investigation(
            workspace_id=item.workspace_id, attention_item_id=item.id, scope_key=scope.key
        )
        session.add(investigation)

    investigation.title = item.title
    investigation.what_happened = narrative["what_happened"]
    investigation.why_it_matters = narrative["why_it_matters"]
    investigation.contributing_factors = narrative["contributing_factors"]
    investigation.next_steps = narrative["next_steps"]
    investigation.confidence = narrative["confidence"]
    investigation.evidence = evidence
    investigation.llm_calls = llm_calls
    session.commit()
    session.refresh(investigation)

    logger.info(
        "investigation_complete",
        item_id=str(item.id), scope=scope.key, evidence=len(evidence), llm_calls=llm_calls,
    )
    return investigation


def investigate_situation(session: Session, *, situation, scope: Scope, refresh: bool = False) -> Investigation:
    """Investigate a proactive situation directly.

    A situation already carries authorized evidence signals, so it is a
    perfectly good anchor - requiring it to *also* have produced an attention
    item was an accident of the first implementation, and on real data that
    requirement was usually unmet, which meant the deeper investigation was
    silently unavailable exactly where it was most useful.

    The scope is checked against the situation's own `scope_key` rather than
    trusted from the caller: a personal situation can only be investigated in
    that person's scope, and a channel situation only in that channel's. So a
    situation assembled from private mail can never be re-investigated as
    shared team context.
    """
    if situation.scope_key != scope.key:
        raise NotAuthorized("This situation belongs to a different context")

    if not refresh:
        cached = session.execute(
            select(Investigation).where(
                Investigation.situation_id == situation.id, Investigation.scope_key == scope.key
            )
        ).scalar_one_or_none()
        if cached is not None:
            return cached

    # The situation's own evidence is the starting point; correlation then
    # expands outward from the most recent piece, within the same scope.
    anchor = _situation_anchor(session, situation, scope)
    evidence = _gather_evidence_for_situation(session, situation, anchor, scope)

    if evidence:
        narrative, llm_calls = _synthesize_situation(situation, anchor, evidence)
    else:
        narrative, llm_calls = _no_evidence_narrative_for(situation), 0

    investigation = session.execute(
        select(Investigation).where(
            Investigation.situation_id == situation.id, Investigation.scope_key == scope.key
        )
    ).scalar_one_or_none()
    if investigation is None:
        investigation = Investigation(
            workspace_id=situation.workspace_id, situation_id=situation.id, scope_key=scope.key
        )
        session.add(investigation)

    investigation.title = situation.title
    investigation.what_happened = narrative["what_happened"]
    investigation.why_it_matters = narrative["why_it_matters"]
    investigation.contributing_factors = narrative["contributing_factors"]
    investigation.next_steps = narrative["next_steps"]
    investigation.confidence = narrative["confidence"]
    investigation.evidence = evidence
    investigation.llm_calls = llm_calls
    session.commit()
    session.refresh(investigation)

    logger.info(
        "situation_investigation_complete",
        situation_id=str(situation.id), scope=scope.key, evidence=len(evidence), llm_calls=llm_calls,
    )
    return investigation


def investigate_commitment(session: Session, *, commitment, scope: Scope, refresh: bool = False) -> Investigation:
    """Why is this commitment late, blocked, or still open?

    A commitment is a third legitimate anchor alongside attention items and
    situations, and the most useful one to investigate: "we said this would
    happen and it hasn't" is exactly the question worth expanding evidence
    around.

    The scope is checked against the commitment's own `scope_key`, so a
    private commitment can only ever be investigated privately.
    """
    if commitment.scope_key != scope.key:
        raise NotAuthorized("This commitment belongs to a different context")

    if not refresh:
        cached = session.execute(
            select(Investigation).where(
                Investigation.commitment_id == commitment.id, Investigation.scope_key == scope.key
            )
        ).scalar_one_or_none()
        if cached is not None:
            return cached

    anchor = _commitment_anchor(session, commitment, scope)
    evidence = _gather_around_anchor(session, commitment.what, anchor, scope, seed=commitment.evidence)

    if evidence:
        narrative, llm_calls = _synthesize_commitment(commitment, anchor, evidence)
    else:
        narrative, llm_calls = _no_commitment_evidence(commitment), 0

    investigation = session.execute(
        select(Investigation).where(
            Investigation.commitment_id == commitment.id, Investigation.scope_key == scope.key
        )
    ).scalar_one_or_none()
    if investigation is None:
        investigation = Investigation(
            workspace_id=commitment.workspace_id, commitment_id=commitment.id, scope_key=scope.key
        )
        session.add(investigation)

    investigation.title = commitment.what
    investigation.what_happened = narrative["what_happened"]
    investigation.why_it_matters = narrative["why_it_matters"]
    investigation.contributing_factors = narrative["contributing_factors"]
    investigation.next_steps = narrative["next_steps"]
    investigation.confidence = narrative["confidence"]
    investigation.evidence = evidence
    investigation.llm_calls = llm_calls
    session.commit()
    session.refresh(investigation)

    logger.info(
        "commitment_investigation_complete",
        commitment_id=str(commitment.id), scope=scope.key, evidence=len(evidence), llm_calls=llm_calls,
    )
    return investigation


def _commitment_anchor(session: Session, commitment, scope: Scope) -> Signal | None:
    """The signal a commitment came from, re-checked against the scope.

    A manual commitment has none, and that is fine - correlation then works
    from its wording alone.
    """
    if commitment.source_signal_id is None:
        return None
    signal = session.get(Signal, commitment.source_signal_id)
    if signal is None or signal.connection_id not in scope.connection_ids:
        return None
    return signal


def _gather_around_anchor(
    session: Session, subject: str, anchor: Signal | None, scope: Scope, *, seed: list[dict] | None = None
) -> list[dict]:
    """Shared correlation walk, used by both the situation and commitment
    anchors so there is one implementation rather than several that drift."""
    if not scope.connection_ids:
        return []

    found: dict[uuid.UUID, dict] = {}
    for entry in seed or []:
        signal = session.get(Signal, uuid.UUID(entry["signal_id"]))
        if signal is not None and signal.connection_id in scope.connection_ids:
            found[signal.id] = _as_evidence(signal, "same_thread")

    def add(signal: Signal, relation: str) -> None:
        if signal.id not in found:
            found[signal.id] = _as_evidence(signal, relation)

    if anchor is not None:
        for signal in _same_thread(session, anchor, scope):
            add(signal, "same_thread")
        for signal in _same_correspondent(session, anchor, scope):
            add(signal, "same_correspondent")

    for signal in _shared_subject(session, subject, scope, exclude=anchor):
        add(signal, "shared_subject")

    when = _aware_dt(anchor.occurred_at) if anchor is not None else None
    if when is not None:
        for signal in _around(session, when, scope):
            add(signal, "around_the_same_time")

    ranked = sorted(found.values(), key=lambda e: (_RELATION_RANK[e["_rank_relation"]], -_recency_key(e)))
    for entry in ranked:
        entry.pop("_rank_relation", None)
    return ranked[:MAX_EVIDENCE]


def _no_commitment_evidence(commitment) -> dict:
    return {
        "what_happened": f"Nothing in this context references \"{commitment.what}\".",
        "why_it_matters": "Sentinel found no authorized activity related to this commitment, so it "
                          "cannot say whether it has progressed.",
        "contributing_factors": [],
        "next_steps": ["Check with the owner directly."],
        "confidence": 0.2,
    }


def _synthesize_commitment(commitment, anchor: Signal | None, evidence: list[dict]) -> tuple[dict, int]:
    facts = {
        "commitment": commitment.what,
        "owner": commitment.owner_label,
        "due": commitment.due_at.isoformat() if commitment.due_at else None,
        "status": commitment.status.value,
        "related_activity": [
            {k: e[k] for k in ("kind", "title", "actor", "occurred_at", "relation")} for e in evidence
        ],
    }
    try:
        result = LLMClient().complete_json(
            system=(
                "You are Sentinel, investigating why a commitment is still open. You are given the "
                "commitment and the related activity retrieved around it. "
                "STRICT RULES: reason ONLY from the supplied data - never invent events or causes. "
                "Do NOT claim the commitment is complete unless the evidence plainly says so; if the "
                "evidence is silent, say that it is silent and lower your confidence. Plain text. "
                "what_happened: 2-3 sentences on what the activity shows about this commitment. "
                "why_it_matters: 1-2 sentences on the consequence of it staying open. "
                "contributing_factors: up to 3 short strings grounded in the activity, or empty. "
                "next_steps: up to 3 short concrete actions. confidence: 0-1. "
                'Return JSON: {"what_happened": "...", "why_it_matters": "...", '
                '"contributing_factors": ["..."], "next_steps": ["..."], "confidence": 0.0}'
            ),
            user=f"Investigation data: {facts}",
        )
        return {
            "what_happened": (result.get("what_happened") or "").strip() or commitment.what,
            "why_it_matters": (result.get("why_it_matters") or "").strip() or "",
            "contributing_factors": [str(f) for f in (result.get("contributing_factors") or [])][:3],
            "next_steps": [str(s) for s in (result.get("next_steps") or [])][:3],
            "confidence": _clamp(result.get("confidence")),
        }, 1
    except LLMError:
        logger.warning("commitment_investigation_llm_unavailable")
        kinds = sorted({e["kind"] for e in evidence})
        return {
            "what_happened": f"{commitment.what}. Sentinel found {len(evidence)} related items "
                             f"({', '.join(kinds)}) but could not reach the language model.",
            "why_it_matters": "",
            "contributing_factors": [],
            "next_steps": ["Review the evidence below directly."],
            "confidence": 0.3,
        }, 0


def _situation_anchor(session: Session, situation, scope: Scope) -> Signal | None:
    """The most recent signal behind the situation, re-checked against scope.

    Re-checked rather than trusted: the situation's evidence was authorized
    when it was detected, and a connection may have been excluded since.
    """
    best = None
    for entry in situation.evidence:
        signal = session.get(Signal, uuid.UUID(entry["signal_id"]))
        if signal is None or signal.connection_id not in scope.connection_ids:
            continue
        if best is None or signal.occurred_at > best.occurred_at:
            best = signal
    return best


def _gather_evidence_for_situation(session: Session, situation, anchor: Signal | None, scope: Scope) -> list[dict]:
    """The situation's own signals, plus whatever correlates with the anchor.

    Delegates to the shared correlation walk so item, situation and commitment
    investigations cannot drift into three different notions of "related".
    """
    return _gather_around_anchor(session, situation.title, anchor, scope, seed=situation.evidence)


def _no_evidence_narrative_for(situation) -> dict:
    return {
        "what_happened": situation.what_is_developing or situation.title,
        "why_it_matters": "The signals behind this situation are no longer readable in this context, "
                          "so there is nothing left to correlate.",
        "contributing_factors": [],
        "next_steps": ["Open the situation's evidence directly."],
        "confidence": 0.2,
    }


def _synthesize_situation(situation, anchor: Signal | None, evidence: list[dict]) -> tuple[dict, int]:
    facts = {
        "situation": situation.title,
        "kind": situation.kind.value,
        "status": situation.status.value,
        "detected_because": situation.what_is_developing,
        "when": (anchor.occurred_at.isoformat() if anchor is not None and anchor.occurred_at else None),
        "related_activity": [
            {k: e[k] for k in ("kind", "title", "actor", "occurred_at", "relation")} for e in evidence
        ],
    }
    try:
        result = LLMClient().complete_json(
            system=(
                "You are Sentinel, investigating a developing situation you already detected. "
                "You are given the situation and the related activity retrieved around it. "
                "STRICT RULES: reason ONLY from the supplied data - never invent events, systems or "
                "causes. If the evidence is thin, say so and lower your confidence rather than "
                "speculating. Plain text, no markdown. "
                "what_happened: 2-3 sentences of what the evidence shows. "
                "why_it_matters: 1-2 sentences on the practical consequence. "
                "contributing_factors: up to 3 short strings, each grounded in the related activity; "
                "empty list if unsupported. next_steps: up to 3 short concrete actions. "
                "confidence: 0-1 for how well the evidence supports your reading. "
                'Return JSON: {"what_happened": "...", "why_it_matters": "...", '
                '"contributing_factors": ["..."], "next_steps": ["..."], "confidence": 0.0}'
            ),
            user=f"Investigation data: {facts}",
        )
        return {
            "what_happened": (result.get("what_happened") or "").strip() or situation.title,
            "why_it_matters": (result.get("why_it_matters") or "").strip() or (situation.why_it_matters or ""),
            "contributing_factors": [str(f) for f in (result.get("contributing_factors") or [])][:3],
            "next_steps": [str(s) for s in (result.get("next_steps") or [])][:3],
            "confidence": _clamp(result.get("confidence")),
        }, 1
    except LLMError:
        logger.warning("situation_investigation_llm_unavailable")
        kinds = sorted({e["kind"] for e in evidence})
        return {
            "what_happened": f"{situation.title}. Sentinel found {len(evidence)} related items "
                             f"({', '.join(kinds)}) but could not reach the language model.",
            "why_it_matters": situation.why_it_matters or "",
            "contributing_factors": [],
            "next_steps": ["Review the evidence below directly."],
            "confidence": 0.3,
        }, 0


def _aware_dt(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _assert_in_scope(item: AttentionItem, scope: Scope) -> None:
    if item.origin == AttentionOrigin.MANUAL:
        # A manual reminder is the author's own note; it has no external
        # source to investigate and no connection to authorize against.
        raise NotAuthorized("A manual reminder has no external evidence to investigate")
    if item.connection_id is None or item.connection_id not in scope.connection_ids:
        raise NotAuthorized("This item's source is not authorized in this context")


# --- retrieval: deterministic, scoped, one relationship at a time ----------


def _anchor_signal(session: Session, item: AttentionItem, scope: Scope) -> Signal | None:
    """The signal the attention item was detected from.

    Absent for `finding` items (an agent's conclusion, not one signal) and
    for anything whose signal has since been re-synced away. Its absence
    degrades the investigation; it never fails it.
    """
    external_id = item.dedupe_key.split(":", 1)[1] if ":" in item.dedupe_key else None
    if external_id is None or item.connection_id is None:
        return None
    # Meeting keys carry a trailing occurrence date.
    if item.dedupe_key.startswith("meeting:"):
        external_id = external_id.rsplit(":", 1)[0]

    return session.execute(
        select(Signal).where(Signal.connection_id == item.connection_id, Signal.external_id == external_id)
    ).scalars().first()


def _gather_evidence(session: Session, item: AttentionItem, anchor: Signal | None, scope: Scope) -> list[dict]:
    """Follow each relationship outward, then rank and cap.

    Every query is filtered to `scope.connection_ids`, so an unauthorized
    connection is unreachable rather than filtered out afterwards.
    """
    if not scope.connection_ids:
        return []

    when = anchor.occurred_at if anchor is not None else (item.due_at or item.created_at)
    found: dict[uuid.UUID, dict] = {}

    def add(signal: Signal, relation: str) -> None:
        if anchor is not None and signal.id == anchor.id:
            return  # the anchor is the subject, not evidence about itself
        existing = found.get(signal.id)
        if existing is None or _RELATION_RANK[relation] < _RELATION_RANK[existing["_rank_relation"]]:
            found[signal.id] = _as_evidence(signal, relation)

    if anchor is not None:
        for signal in _same_thread(session, anchor, scope):
            add(signal, "same_thread")
        for signal in _same_correspondent(session, anchor, scope):
            add(signal, "same_correspondent")

    for signal in _shared_subject(session, item.title, scope, exclude=anchor):
        add(signal, "shared_subject")

    if when is not None:
        for signal in _around(session, when, scope):
            add(signal, "around_the_same_time")

    ranked = sorted(
        found.values(),
        key=lambda e: (_RELATION_RANK[e["_rank_relation"]], -_recency_key(e)),
    )
    for entry in ranked:
        entry.pop("_rank_relation", None)
    return ranked[:MAX_EVIDENCE]


def _same_thread(session: Session, anchor: Signal, scope: Scope) -> list[Signal]:
    thread_id = (anchor.payload or {}).get("thread_id")
    if not thread_id:
        return []
    rows = session.execute(
        select(Signal).where(Signal.connection_id.in_(scope.connection_ids), Signal.type == SignalType.EMAIL)
    ).scalars().all()
    return [s for s in rows if (s.payload or {}).get("thread_id") == thread_id]


def _same_correspondent(session: Session, anchor: Signal, scope: Scope) -> list[Signal]:
    """Other recent activity from the same person or system.

    Matched on `actor`, which every provider populates - the sender for mail,
    the author for a commit or PR. Bounded in time: what this correspondent
    sent last quarter is not evidence about today.
    """
    if not anchor.actor:
        return []
    since = anchor.occurred_at - CORRESPONDENT_WINDOW
    until = anchor.occurred_at + CORRESPONDENT_WINDOW
    return list(session.execute(
        select(Signal)
        .where(
            Signal.connection_id.in_(scope.connection_ids),
            Signal.actor == anchor.actor,
            Signal.occurred_at >= since,
            Signal.occurred_at <= until,
        )
        .order_by(Signal.occurred_at.desc())
        .limit(8)
    ).scalars())


def _shared_subject(session: Session, title: str, scope: Scope, *, exclude: Signal | None) -> list[Signal]:
    """Signals whose own title shares a meaningful word with this one.

    Reuses meeting_prep's keyword rule, which already knows that "Sync" and
    "Meeting" are not search terms while "Q3" and "v2" are. Matching happens
    in Python rather than SQL because titles live inside a JSON payload whose
    key differs per provider, and a LIKE over JSON would be both unindexable
    and provider-specific.
    """
    keywords = [k.lower() for k in meaningful_keywords(title)][:6]
    if not keywords:
        return []

    rows = session.execute(
        select(Signal).where(Signal.connection_id.in_(scope.connection_ids)).order_by(Signal.occurred_at.desc()).limit(400)
    ).scalars().all()

    matched = []
    for signal in rows:
        if exclude is not None and signal.id == exclude.id:
            continue
        text = _signal_title(signal).lower()
        if any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords):
            matched.append(signal)
        if len(matched) >= 8:
            break
    return matched


def _around(session: Session, when: datetime, scope: Scope) -> list[Signal]:
    """What else happened nearby, across every authorized provider.

    This is the cross-source correlation: a deployment failure and the
    commits and meetings around it are related by time, not by sender or
    subject.

    Bulk mail is excluded here, and only here. Measured against the real
    inbox, an unfiltered time window returned Pinterest digests, Instagram
    suggestions and freelancing spam as "related activity" - and the model
    dutifully wove a coincidental Google security alert into a contributing
    factor, which is worse than returning nothing. Temporal proximity is the
    weakest relationship of the four and the only one with no explicit link
    to the anchor, so it is the one that has to earn its place.

    The other three relations are deliberately not filtered: a bulk sender
    who is *in the thread* or *is the correspondent* is genuinely relevant,
    and the same noise rule that improved attention precision from ~17% to
    ~80% (Phase 2v) would otherwise throw that away.
    """
    candidates = list(session.execute(
        select(Signal)
        .where(
            Signal.connection_id.in_(scope.connection_ids),
            Signal.occurred_at >= when - NEIGHBOUR_WINDOW,
            Signal.occurred_at <= when + NEIGHBOUR_WINDOW,
        )
        .order_by(Signal.occurred_at.desc())
        .limit(40)
    ).scalars())

    counts = sender_counts([s.payload or {} for s in candidates if s.type == SignalType.EMAIL])
    kept = []
    for signal in candidates:
        if signal.type == SignalType.EMAIL and noise_reason(signal.payload or {}, counts) is not None:
            continue
        kept.append(signal)
        if len(kept) >= 10:
            break
    return kept


# --- shaping --------------------------------------------------------------


def _signal_title(signal: Signal) -> str:
    payload = signal.payload or {}
    return payload.get("subject") or payload.get("title") or payload.get("name") or f"{signal.type.value} {signal.external_id}"


def _signal_url(signal: Signal) -> str | None:
    payload = signal.payload or {}
    if payload.get("url"):
        return payload["url"]
    if signal.type == SignalType.EMAIL:
        return f"https://mail.google.com/mail/u/0/#all/{signal.external_id}"
    return None


def _as_evidence(signal: Signal, relation: str) -> dict:
    return {
        "signal_id": str(signal.id),
        "kind": signal.type.value,
        "title": _signal_title(signal),
        "actor": signal.actor,
        "occurred_at": signal.occurred_at.isoformat() if signal.occurred_at else None,
        "url": _signal_url(signal),
        "relation": relation,
        "relation_label": _RELATION_LABEL[relation],
        "_rank_relation": relation,
    }


def _recency_key(entry: dict) -> float:
    raw = entry.get("occurred_at")
    if not raw:
        return 0.0
    return datetime.fromisoformat(raw).timestamp()


def _no_evidence_narrative(item: AttentionItem) -> dict:
    return {
        "what_happened": item.why or item.title,
        "why_it_matters": "Sentinel found no related activity in the data this context is authorized to read, "
                          "so there is nothing to correlate it against yet.",
        "contributing_factors": [],
        "next_steps": ["Open the original item to judge it directly."],
        "confidence": 0.2,
    }


def _synthesize(item: AttentionItem, anchor: Signal | None, evidence: list[dict]) -> tuple[dict, int]:
    """The one LLM call. Everything above this line was deterministic.

    The model is given only what was retrieved, and is told to reason from it
    rather than from anything it knows about the world - an investigation
    that invents a cause is worse than one that admits it found little.
    """
    facts = {
        "item": {
            "title": item.title,
            "why_flagged": item.why,
            "type": item.type.value,
            "source": item.source_provider,
            "when": (anchor.occurred_at.isoformat() if anchor is not None and anchor.occurred_at else None),
        },
        "related_activity": [
            {k: e[k] for k in ("kind", "title", "actor", "occurred_at", "relation")} for e in evidence
        ],
    }

    try:
        result = LLMClient().complete_json(
            system=(
                "You are Sentinel, investigating one item that needs a user's attention. "
                "You are given the item and the related activity Sentinel retrieved around it. "
                "STRICT RULES: reason ONLY from the supplied data - never invent events, names, "
                "systems or causes that do not appear in it. If the evidence is thin, say so and "
                "lower your confidence rather than speculating. Plain text, no markdown. "
                "what_happened: 2-3 sentences of what the evidence shows. "
                "why_it_matters: 1-2 sentences on the practical consequence for this person. "
                "contributing_factors: up to 3 short strings, each grounded in a specific piece of "
                "the related activity; empty list if the evidence does not support any. "
                "next_steps: up to 3 short, concrete, practical actions. "
                "confidence: a number 0-1 for how well the evidence supports your reading. "
                'Return JSON: {"what_happened": "...", "why_it_matters": "...", '
                '"contributing_factors": ["..."], "next_steps": ["..."], "confidence": 0.0}'
            ),
            user=f"Investigation data: {facts}",
        )
        return {
            "what_happened": (result.get("what_happened") or "").strip() or item.title,
            "why_it_matters": (result.get("why_it_matters") or "").strip() or item.why,
            "contributing_factors": [str(f) for f in (result.get("contributing_factors") or [])][:3],
            "next_steps": [str(s) for s in (result.get("next_steps") or [])][:3],
            "confidence": _clamp(result.get("confidence")),
        }, 1
    except LLMError:
        logger.warning("investigation_llm_unavailable_using_fallback")
        # Degrades in charm, never in correctness: the evidence was retrieved
        # deterministically and is still shown in full. Same discipline as
        # Catch Me Up and channel briefings.
        kinds = sorted({e["kind"] for e in evidence})
        return {
            "what_happened": f"{item.title}. Sentinel found {len(evidence)} related items "
                             f"({', '.join(kinds)}) but could not reach the language model to interpret them.",
            "why_it_matters": item.why,
            "contributing_factors": [],
            "next_steps": ["Review the evidence below directly."],
            "confidence": 0.3,
        }, 0


def _clamp(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5
