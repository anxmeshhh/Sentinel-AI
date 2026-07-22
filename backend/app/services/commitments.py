"""Commitment Intelligence: what did we say would happen, and is it happening?

## What is and isn't built, and why

The module was scoped by measurement rather than by ambition
(`scripts/audit_commitments.py` and `audit_commitment_bodies.py`, run against
the real corpus):

| Source | Finding | Status |
|---|---|---|
| Manual statements | always available | real-data verified |
| GitHub issues/PRs | owner + subject + observable closure | functionally tested, 0 real signals |
| Message prose | 0 promise subjects in 190; **2 of 40 bodies matched, both false positives** | functionally tested, gated hard |

Prose extraction lives in `commitment_extraction.py`, deliberately separate:
it is the only part of Sentinel that reads message content, and keeping it at
arm's length makes that boundary visible. Bodies are fetched live and
discarded; only structured fields survive. Because the measured false-positive
rate on real prose was 2/2, anything the model is not highly confident about
becomes a SUGGESTED commitment that *asks* rather than asserts.

## Deterministic wherever it can be

Every lifecycle transition here - due soon, at risk, overdue, resolved - is
derived from a date, a source's own state field, or a person's explicit
action. No model is consulted about whether a commitment is late, and none is
consulted to summarise one. The single exception is prose extraction, which
is bounded (at most 10 pre-filtered bodies per scope per run), gated by
confidence, and cannot assert anything on its own.

That split is the point: what Sentinel *claims* is deterministic, and what it
*suspects* is clearly marked as a question.

## Resolution is evidence, never similarity

A TRACKED commitment resolves when its own source signal says so - the issue
closed, the PR merged. It never resolves because some other signal looked
similar; a commitment wrongly marked done is worse than one left open, since
the whole point is that promises don't quietly disappear.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.commitment import Commitment, CommitmentSource, CommitmentStatus
from app.models.signal import Signal, SignalType
from app.services.commitment_extraction import extract_commitments
from app.services.investigation import Scope

logger = structlog.get_logger("sentinel.commitments")

DUE_SOON_HORIZON = timedelta(hours=72)
# How long a due-soon commitment can show no progress before it is called out.
# Deliberately generous: "at risk" should mean something.
STALE_AFTER = timedelta(days=3)
LOOKBACK = timedelta(days=90)

# SUGGESTED is included: a question nobody sees is a question nobody answers.
# It sorts last, and the UI renders it as a prompt rather than as a fact.
_LIVE = (
    CommitmentStatus.PENDING,
    CommitmentStatus.DUE_SOON,
    CommitmentStatus.AT_RISK,
    CommitmentStatus.OVERDUE,
    CommitmentStatus.SUGGESTED,
)


class CommitmentError(Exception):
    pass


class NotAuthorized(CommitmentError):
    pass


@dataclass
class TrackedCandidate:
    key: str
    what: str
    owner_label: str | None
    due_at: datetime | None
    signal: Signal
    last_progress_at: datetime | None
    resolved_reason: str | None


# --- reading ---------------------------------------------------------------


def list_commitments(session: Session, scope: Scope, *, include_closed: bool = False) -> list[Commitment]:
    """This scope's commitments, most urgent first."""
    query = select(Commitment).where(Commitment.scope_key == scope.key)
    if not include_closed:
        query = query.where(Commitment.status.in_(_LIVE))
    rows = list(session.execute(query).scalars())

    order = {
        CommitmentStatus.OVERDUE: 0,
        CommitmentStatus.AT_RISK: 1,
        CommitmentStatus.DUE_SOON: 2,
        CommitmentStatus.PENDING: 3,
        CommitmentStatus.SUGGESTED: 4,  # a question, not an obligation
    }
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(rows, key=lambda c: (order.get(c.status, 9), _aware(c.due_at) or far_future))


# --- manual ----------------------------------------------------------------


def create_manual_commitment(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    scope: Scope,
    what: str,
    user_id: uuid.UUID,
    due_at: datetime | None = None,
    owner_label: str | None = None,
) -> Commitment:
    """A commitment a person stated outright.

    Enters exactly the same lifecycle as a tracked one - a separate reminder
    system that ages differently from the rest is how "what's outstanding?"
    stops having a single answer.
    """
    commitment = Commitment(
        workspace_id=workspace_id,
        scope_key=scope.key,
        commitment_key=f"manual:{uuid.uuid4()}",  # stated twice means two, by definition
        source=CommitmentSource.MANUAL,
        what=what.strip(),
        owner_label=owner_label,
        due_at=_aware(due_at),
        confidence=1.0,  # nobody needs convincing that they said it
        created_by_user_id=user_id,
        evidence=[],
    )
    commitment.status = _status_for(commitment, datetime.now(timezone.utc))
    session.add(commitment)
    session.commit()
    session.refresh(commitment)
    return commitment


def resolve_commitment(session: Session, commitment: Commitment, *, reason: str) -> Commitment:
    commitment.status = CommitmentStatus.RESOLVED
    commitment.resolved_at = datetime.now(timezone.utc)
    commitment.resolution_reason = reason
    session.commit()
    session.refresh(commitment)
    return commitment


def dismiss_commitment(session: Session, commitment: Commitment, *, reason: str | None = None) -> Commitment:
    """Not the same as resolved. "This never mattered" and "this got done"
    are different facts, and collapsing them would make the record useless
    for judging whether commitments actually get met."""
    commitment.status = CommitmentStatus.DISMISSED
    commitment.resolved_at = datetime.now(timezone.utc)
    commitment.resolution_reason = reason or "Dismissed"
    session.commit()
    session.refresh(commitment)
    return commitment


def confirm_commitment(session: Session, commitment: Commitment) -> Commitment:
    """A person answered "yes, track this" to a suggested commitment.

    Confidence goes to 1.0 because it is no longer the model's opinion - a
    human confirmed it, which is the same standing a manual commitment has.
    """
    if commitment.status == CommitmentStatus.SUGGESTED:
        commitment.confidence = 1.0
        commitment.status = _status_for(commitment, datetime.now(timezone.utc))
        session.commit()
        session.refresh(commitment)
    return commitment


def reopen_commitment(session: Session, commitment: Commitment) -> Commitment:
    commitment.resolved_at = None
    commitment.resolution_reason = None
    commitment.status = _status_for(commitment, datetime.now(timezone.utc))
    session.commit()
    session.refresh(commitment)
    return commitment


# --- automatic detection + lifecycle --------------------------------------


def refresh_commitments(session: Session, workspace_id: uuid.UUID, scope: Scope) -> list[Commitment]:
    """Detect tracked commitments, then age every commitment in this scope.

    Two passes, and the second one matters more day to day: most of what this
    module does is notice that time has passed.
    """
    now = datetime.now(timezone.utc)

    if scope.connection_ids:
        for candidate in _detect_tracked(session, scope, now):
            _upsert_tracked(session, workspace_id, scope, candidate, now)
        # Prose extraction, gated hard and bounded - see
        # commitment_extraction.py. Never lets a provider or model failure
        # take down the deterministic half of this refresh.
        try:
            extract_commitments(session, workspace_id, scope)
        except Exception:
            session.rollback()
            logger.exception("commitment_extraction_failed", scope=scope.key)

    for commitment in session.execute(
        select(Commitment).where(Commitment.scope_key == scope.key)
    ).scalars():
        if commitment.status in (
            CommitmentStatus.RESOLVED, CommitmentStatus.DISMISSED, CommitmentStatus.SUGGESTED
        ):
            # A suggestion is not yet an obligation, so it does not age. An
            # unanswered question turning itself into "OVERDUE" would be
            # Sentinel asserting exactly what it was unsure enough to ask.
            continue
        commitment.status = _status_for(commitment, now)

    session.commit()
    return list_commitments(session, scope)


def refresh_commitments_for_workspace(session: Session, workspace_id: uuid.UUID) -> int:
    """Background entry point, per scope - same reasoning as proactive: each
    authorized scope is refreshed on its own, so a private commitment cannot
    be computed into a channel's list."""
    from app.models.connection import Connection
    from app.models.team import Team
    from app.services.investigation import channel_scope, personal_scope

    refreshed = 0
    owner_ids = set(session.execute(
        select(Connection.user_id).where(Connection.workspace_id == workspace_id)
    ).scalars())
    # Personal scopes include people with no connection at all: a manual
    # commitment still has to age even if its owner has connected nothing.
    manual_scopes = set(session.execute(
        select(Commitment.scope_key).where(Commitment.workspace_id == workspace_id)
    ).scalars())

    for user_id in owner_ids:
        try:
            refresh_commitments(session, workspace_id, personal_scope(session, workspace_id, user_id))
            refreshed += 1
        except Exception:
            session.rollback()
            logger.exception("commitment_personal_scope_failed", user_id=str(user_id))

    for team_id in list(session.execute(select(Team.id).where(Team.workspace_id == workspace_id)).scalars()):
        try:
            refresh_commitments(session, workspace_id, channel_scope(session, team_id))
            refreshed += 1
        except Exception:
            session.rollback()
            logger.exception("commitment_channel_scope_failed", team_id=str(team_id))

    # Anything left over is a scope with commitments but no live connection
    # (all-manual). Age those too, or a manual reminder would never go overdue.
    handled = {f"personal:{u}" for u in owner_ids}
    for scope_key in manual_scopes - handled:
        if scope_key.startswith("channel:"):
            continue  # already covered above
        try:
            refresh_commitments(session, workspace_id, Scope(key=scope_key))
            refreshed += 1
        except Exception:
            session.rollback()
            logger.exception("commitment_manual_scope_failed", scope_key=scope_key)

    logger.info("commitment_workspace_refresh", workspace_id=str(workspace_id), scopes=refreshed)
    return refreshed


def _detect_tracked(session: Session, scope: Scope, now: datetime) -> list[TrackedCandidate]:
    """Structured signals that genuinely carry a commitment.

    An issue or PR assigned to somebody is a commitment in the only sense
    that can be verified: there is an owner, a stated piece of work, and a
    state field that will eventually say whether it happened. Nothing here is
    inferred from language.

    Unassigned work is deliberately skipped - "somebody should do this" is a
    wish, and tracking it as a commitment is how a reminder list becomes
    noise nobody trusts.

    NOTE: functionally tested, awaiting real-data validation. The corpus
    currently holds zero issue/PR signals because no GitHub connection is
    configured.
    """
    since = now - LOOKBACK
    signals = session.execute(
        select(Signal).where(
            Signal.connection_id.in_(scope.connection_ids),
            Signal.type.in_([SignalType.ISSUE, SignalType.PR]),
            Signal.occurred_at >= since,
        )
    ).scalars().all()

    candidates = []
    for signal in signals:
        payload = signal.payload or {}
        owner = _assignee(payload)
        if not owner:
            continue

        title = payload.get("title") or f"#{payload.get('number', '?')}"
        closed_reason = _closure_reason(payload)
        candidates.append(TrackedCandidate(
            key=f"{signal.type.value}:{signal.external_id}",
            what=str(title)[:500],
            owner_label=owner,
            due_at=_parse(payload.get("due_on") or payload.get("milestone_due_on")),
            signal=signal,
            last_progress_at=_parse(payload.get("updated_at")) or _aware(signal.occurred_at),
            resolved_reason=closed_reason,
        ))
    return candidates


def _upsert_tracked(
    session: Session, workspace_id: uuid.UUID, scope: Scope, candidate: TrackedCandidate, now: datetime
) -> Commitment:
    commitment = session.execute(
        select(Commitment).where(
            Commitment.scope_key == scope.key, Commitment.commitment_key == candidate.key
        )
    ).scalar_one_or_none()

    if commitment is None:
        commitment = Commitment(
            workspace_id=workspace_id,
            scope_key=scope.key,
            commitment_key=candidate.key,
            source=CommitmentSource.TRACKED,
            confidence=0.9,
        )
        session.add(commitment)

    commitment.what = candidate.what
    commitment.owner_label = candidate.owner_label
    commitment.due_at = candidate.due_at
    commitment.source_signal_id = candidate.signal.id
    commitment.last_progress_at = candidate.last_progress_at
    commitment.evidence = [_evidence(candidate.signal)]

    if candidate.resolved_reason:
        # Resolution from the source's own state - a fact, not a guess. A
        # person's manual resolution is never overwritten by re-detection,
        # but a genuine closure does close a manual re-open.
        commitment.status = CommitmentStatus.RESOLVED
        commitment.resolved_at = commitment.resolved_at or now
        commitment.resolution_reason = candidate.resolved_reason
    elif commitment.status in (CommitmentStatus.RESOLVED, CommitmentStatus.DISMISSED):
        # The source reopened. Trust the source.
        commitment.resolved_at = None
        commitment.resolution_reason = None
        commitment.status = _status_for(commitment, now)
    else:
        commitment.status = _status_for(commitment, now)
    return commitment


def _status_for(commitment: Commitment, now: datetime) -> CommitmentStatus:
    """Time and evidence only. Nothing here is a judgement call."""
    due = _aware(commitment.due_at)
    if due is None:
        return CommitmentStatus.PENDING
    if due < now:
        return CommitmentStatus.OVERDUE
    if due - now > DUE_SOON_HORIZON:
        return CommitmentStatus.PENDING

    # Due soon. "At risk" requires an actual observation of no progress, so a
    # manual commitment - which has no progress signal to read - is never
    # labelled at risk rather than being guessed about.
    progress = _aware(commitment.last_progress_at)
    if progress is not None and now - progress > STALE_AFTER:
        return CommitmentStatus.AT_RISK
    return CommitmentStatus.DUE_SOON


# --- helpers ---------------------------------------------------------------


def _assignee(payload: dict) -> str | None:
    for key in ("assignee", "assigned_to", "owner"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict) and value.get("login"):
            return str(value["login"])
    assignees = payload.get("assignees")
    if isinstance(assignees, list) and assignees:
        first = assignees[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict) and first.get("login"):
            return str(first["login"])
    return None


def _closure_reason(payload: dict) -> str | None:
    if payload.get("merged_at"):
        return "The pull request was merged"
    if payload.get("closed_at") or payload.get("state") in ("closed", "CLOSED"):
        return "The issue was closed"
    return None


def _evidence(signal: Signal) -> dict:
    payload = signal.payload or {}
    return {
        "signal_id": str(signal.id),
        "kind": signal.type.value,
        "title": payload.get("title") or payload.get("subject") or signal.external_id,
        "actor": signal.actor,
        "occurred_at": _aware(signal.occurred_at).isoformat(),
        "url": payload.get("url"),
        "relation": "the_commitment",
    }


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _parse(raw) -> datetime | None:
    if isinstance(raw, datetime):
        return _aware(raw)
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return _aware(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None
