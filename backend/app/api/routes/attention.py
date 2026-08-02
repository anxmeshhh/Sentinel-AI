"""Phase 2p: the Attention API - Sentinel's unified "what needs my
attention" feed. Detection itself lives in services/attention_engine.py
(deterministic, no LLM); these routes expose the list, the lifecycle
actions (done/snooze/dismiss), manual reminders, and an on-demand refresh.
"""

import uuid
from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.situation import SituationKind
from app.models.user import User
from app.providers.registry import spec_for
from app.domain.finding import FindingSource, FindingTier
from app.services.connection_state import ConnectionState, connection_state
from app.services.findings import list_findings
from app.services.mail_signals import noise_reason, sender_counts
from app.schemas.attention import (
    AttentionItemOut,
    AttentionStateUpdate,
    CalendarPlanOut,
    ManualReminderCreate,
    ProviderStatusOut,
    SentinelStatusOut,
)
from app.services.attention_engine import list_attention, refresh_attention
from app.services.catchup import build_catchup

router = APIRouter(prefix="/attention", tags=["attention"])


def _to_out(item: AttentionItem) -> AttentionItemOut:
    return AttentionItemOut(
        id=item.id, type=item.type.value, origin=item.origin.value, state=item.state.value,
        source_provider=item.source_provider, title=item.title, why=item.why,
        evidence_url=item.evidence_url, priority=item.priority,
        due_at=item.due_at, snoozed_until=item.snoozed_until, created_at=item.created_at,
    )


def _parse_states(state: str | None) -> list[AttentionState] | None:
    if not state:
        return None
    try:
        return [AttentionState(s.strip()) for s in state.split(",") if s.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid state filter: {state}")


@router.get("", response_model=list[AttentionItemOut])
def get_attention(
    state: str | None = None,  # comma-separated; default: new only
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[AttentionItemOut]:
    """This person's own attention list.

    Scoped to the caller (Phase 3), not to the workspace. In a team workspace
    the attention table holds items detected from every member's connections,
    so returning the workspace's list would show one member the subject lines
    of another's mail. Shared context has its own surface - the channel
    briefing - where the channel's authorization decides what is visible.
    """
    items = list_attention(session, workspace_id, states=_parse_states(state), viewer_user_id=user.id)
    return [_to_out(i) for i in items]


@router.get("/context")
def attention_context(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """Why the attention list looks the way it does.

    An empty feed has three completely different causes - nothing is
    connected, something is connected but hasn't synced yet, or everything
    synced and genuinely nothing needs you - and they call for three
    different responses from the user. Showing one blank message for all
    three reads as "broken", which is exactly the impression an attention
    product cannot afford.

    Pure counts, no LLM, no provider calls.

    Counted over the caller's own connections only, matching the list it
    explains (Phase 3). Counting the workspace would both contradict that
    list - "3 connections, 0 items" - and quantify a teammate's mail volume.
    """
    connections = session.execute(
        select(Connection).where(Connection.workspace_id == workspace_id, Connection.user_id == user.id)
    ).scalars().all()
    synced = [c for c in connections if c.last_synced_at is not None]
    last_synced = max((c.last_synced_at for c in synced), default=None)

    emails = session.execute(
        select(Signal).where(
            Signal.workspace_id == workspace_id,
            Signal.type == SignalType.EMAIL,
            Signal.connection_id.in_([c.id for c in connections]),
        )
    ).scalars().all() if connections else []

    # How many looked important enough to consider, and how many of those
    # were set aside as bulk/automated - so "nothing here" can show its work.
    counts = sender_counts([e.payload for e in emails])
    considered = filtered = 0
    for e in emails:
        labels = set(e.payload.get("label_ids") or [])
        if "UNREAD" not in labels:
            continue
        promotional = bool(labels & {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "SPAM"})
        if not ("STARRED" in labels or ("IMPORTANT" in labels and not promotional)):
            continue
        considered += 1
        if noise_reason(e.payload, counts) is not None:
            filtered += 1

    return {
        "connection_count": len(connections),
        "synced_connection_count": len(synced),
        "last_synced_at": last_synced.isoformat() if last_synced else None,
        "signals_seen": len(emails),
        "considered": considered,
        "filtered_as_noise": filtered,
    }


# Severity order for collapsing one provider's several resources into a single
# line: the worst thing true of any of them is what the card must show.
_STATE_SEVERITY = {
    ConnectionState.TOKEN_REVOKED: 5,
    ConnectionState.ERROR: 4,
    ConnectionState.NEEDS_SETUP: 3,
    ConnectionState.SYNCING: 2,
    ConnectionState.PAUSED: 1,
    ConnectionState.READY: 0,
    ConnectionState.LIVE: 0,  # connected, queried on demand - as healthy as ready
}
_STATE_ERROR = {
    ConnectionState.TOKEN_REVOKED: "authentication expired — reconnect needed",
    ConnectionState.ERROR: "last sync failed",
}


def _operational_summary(situations: list, detected: list) -> str | None:
    """A plain phrase naming what Sentinel found, for the verdict's second
    line. Deterministic - it reads the counts, never an LLM."""
    def n_of(count: int, one: str, many: str) -> str:
        return f"{count} {one if count == 1 else many}"

    parts: list[str] = []
    kinds = Counter(s.kind for s in situations)
    if kinds.get(SituationKind.RESOURCE_STALLED):
        parts.append(n_of(kinds[SituationKind.RESOURCE_STALLED], "stalled repository", "stalled repositories"))
    if kinds.get(SituationKind.SERVICE_JEOPARDY):
        parts.append(n_of(kinds[SituationKind.SERVICE_JEOPARDY], "service at risk", "services at risk"))
    if kinds.get(SituationKind.MEETING_UNPREPARED):
        parts.append(n_of(kinds[SituationKind.MEETING_UNPREPARED], "unprepared meeting", "unprepared meetings"))

    types = Counter(i.type for i in detected)
    type_phrase = {
        AttentionType.IMPORTANT_EMAIL: ("important email", "important emails"),
        AttentionType.STALE_PR: ("stalled pull request", "stalled pull requests"),
        AttentionType.DEADLINE: ("approaching deadline", "approaching deadlines"),
        AttentionType.UPCOMING_MEETING: ("upcoming meeting", "upcoming meetings"),
        AttentionType.FINDING: ("flagged finding", "flagged findings"),
    }
    for t, (one, many) in type_phrase.items():
        if types.get(t):
            parts.append(n_of(types[t], one, many))

    if not parts:
        return None
    body = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"Sentinel detected {body}."


@router.get("/status", response_model=SentinelStatusOut)
def sentinel_status(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> SentinelStatusOut:
    """"Is Sentinel working?" - the trust card at the top of Attention.

    Everything here is a deterministic count over the caller's own
    connections; no LLM, no provider round trips. Per-provider health reuses
    the generic ``connection_state`` so this card and every other surface
    agree on what "ready" or "failing" means. A provider is shown as failing
    only for the two states a person must act on - a dead grant or a sync that
    has never succeeded - so a green card is a green card.
    """
    connections = session.execute(
        select(Connection).where(Connection.workspace_id == workspace_id, Connection.user_id == user.id)
    ).scalars().all()

    signal_counts = dict(session.execute(
        select(Connection.provider, func.count(Signal.id))
        .join(Signal, Signal.connection_id == Connection.id)
        .where(Connection.workspace_id == workspace_id, Connection.user_id == user.id)
        .group_by(Connection.provider)
    ).all())

    # Group by provider, then collapse each provider's resources to one line.
    by_provider: dict = {}
    for c in connections:
        by_provider.setdefault(c.provider, []).append(c)

    providers: list[ProviderStatusOut] = []
    errors: list[str] = []
    for provider, group in by_provider.items():
        spec = spec_for(provider)
        resources = [c for c in group if c.repo]  # a chosen resource, not a bare anchor
        # connection_state now returns LIVE for live-query providers, so the
        # old syncing/error->ready patch here is gone - the state is correct at
        # the source (see services/connection_state.py).
        worst = max((connection_state(c) for c in resources), key=lambda s: _STATE_SEVERITY[s], default=ConnectionState.NEEDS_SETUP)
        ok = worst not in (ConnectionState.ERROR, ConnectionState.TOKEN_REVOKED)
        reason = _STATE_ERROR.get(worst)
        error = None if ok else f"{spec.label} {reason}"
        if error:
            errors.append(error)
        last = max((c.last_synced_at for c in group if c.last_synced_at is not None), default=None)
        providers.append(ProviderStatusOut(
            provider=provider.value,
            label=spec.label,
            ok=ok,
            state=worst.value,
            resource_count=len(resources),
            signal_count=int(signal_counts.get(provider, 0)),
            live=spec.live_query,
            error=error,
            last_synced_at=last,
        ))

    # Meet is not a separate grant - it rides on Calendar events that carry a
    # meeting link. We surface it as its own "checked" line, honestly labelled,
    # because "did you look at my meetings?" is a real question to the user and
    # we truthfully do analyse those links. Its signals are a subset of
    # Calendar's, so it never inflates the total - only the provider list.
    cal = next((p for p in providers if p.provider == Provider.GOOGLE_CALENDAR.value), None)
    if cal is not None:
        cal_events = session.execute(
            select(Signal.payload)
            .join(Connection, Signal.connection_id == Connection.id)
            .where(
                Connection.workspace_id == workspace_id,
                Connection.user_id == user.id,
                Signal.type == SignalType.CALENDAR_EVENT,
            )
        ).scalars().all()
        meet_count = sum(1 for p in cal_events if p and p.get("has_meeting_link"))
        providers.append(ProviderStatusOut(
            provider="google_meet",
            label="Meet",
            ok=cal.ok,  # if Calendar is failing, so is our view of Meet
            state=cal.state,
            resource_count=0,  # not a resource of its own - a lens on Calendar
            signal_count=meet_count,
            live=False,
            error=None,  # Calendar already reports the underlying error
            last_synced_at=cal.last_synced_at,
            note="via Calendar",
        ))

    providers.sort(key=lambda p: p.label.lower())

    # The operational state is the UNION of both surfaces this page shows:
    # attention items (Now) AND proactive situations (Risks) - now read through
    # the one canonical Finding stream (Intelligence Core, Phase 1) rather than
    # querying each pipeline here. The tier (critical/review/reminder) is
    # computed once, in services/findings.py, so a card and this verdict can
    # never disagree on what "critical" means.
    findings = list_findings(session, workspace_id, viewer_user_id=user.id)
    critical_count = sum(1 for f in findings if f.tier is FindingTier.CRITICAL)
    review_count = sum(1 for f in findings if f.tier is FindingTier.REVIEW)
    reminder_count = sum(1 for f in findings if f.tier is FindingTier.REMINDER)
    findings_count = critical_count + review_count

    # The deterministic summary phrasing still reads the underlying rows (via
    # the canonical finding's transitional ``raw`` handle), reconstructing the
    # exact two lists it has always taken: proactive situations, and detected
    # (non-reminder) attention items.
    situations = [f.raw for f in findings if f.source is FindingSource.PROACTIVE]
    detected = [f.raw for f in findings if f.source is FindingSource.ATTENTION and f.tier is not FindingTier.REMINDER]
    summary = _operational_summary(situations, detected)
    last_synced = max((c.last_synced_at for c in connections if c.last_synced_at is not None), default=None)

    return SentinelStatusOut(
        healthy=not errors,
        provider_count=len(providers),
        resource_count=sum(p.resource_count for p in providers),
        # Summed from the real per-provider ingest counts, not the provider
        # list - so Meet, whose signals are a subset of Calendar's, is shown as
        # its own line without being added to the total twice.
        signals_analysed=sum(int(v) for v in signal_counts.values()),
        findings_count=findings_count,
        critical_count=critical_count,
        review_count=review_count,
        reminder_count=reminder_count,
        summary=summary,
        last_synced_at=last_synced,
        providers=providers,
        errors=errors,
    )


@router.get("/catchup")
def catch_me_up(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """What changed since this user last looked at this workspace - see
    services/catchup.py. Calling this advances the last-seen marker, so the
    frontend calls it once per dashboard load."""
    return build_catchup(session, workspace_id, user.id)


@router.post("/refresh", response_model=list[AttentionItemOut])
def refresh(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[AttentionItemOut]:
    """On-demand re-detection - also runs automatically after every sync
    cycle, so this exists for the "refresh" button, not as the primary path.

    Detection covers the workspace; the list returned is the caller's own.
    """
    items = refresh_attention(session, workspace_id, viewer_user_id=user.id)
    return [_to_out(i) for i in items]


@router.post("", response_model=AttentionItemOut, status_code=201)
def create_manual_reminder(
    payload: ManualReminderCreate,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> AttentionItemOut:
    item = AttentionItem(
        workspace_id=workspace_id,
        created_by_user_id=user.id,
        type=AttentionType.MANUAL,
        origin=AttentionOrigin.MANUAL,
        state=AttentionState.NEW,
        source_provider=None,
        dedupe_key=f"manual:{uuid.uuid4()}",  # manual items never collide/dedupe
        title=payload.title,
        why=payload.why or "Reminder you created",
        evidence_url=payload.evidence_url,
        priority=0.65,
        due_at=payload.due_at,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _to_out(item)


@router.post("/{item_id}/calendar-plan", response_model=CalendarPlanOut)
def build_calendar_plan(
    item_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> CalendarPlanOut:
    """Phase 2t: turn a dated item into a *proposed* calendar event.

    Deliberately deterministic - the title and time come straight from the
    item, so what the user confirms is exactly what they already saw. This
    endpoint writes nothing; the client sends the returned plan to
    /connections/google/command/execute after the user confirms.
    """
    item = session.get(AttentionItem, item_id)
    if item is None or item.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Attention item not found")
    if item.due_at is None:
        raise HTTPException(status_code=400, detail="This item has no date, so there's nothing to put on a calendar")

    # A deadline is a point in time; a 30-minute block gives it presence in
    # the day without pretending to know how long the work takes.
    start = item.due_at
    return CalendarPlanOut(title=item.title[:200], start=start, end=start + timedelta(minutes=30))


@router.patch("/{item_id}", response_model=AttentionItemOut)
def update_state(
    item_id: uuid.UUID,
    payload: AttentionStateUpdate,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> AttentionItemOut:
    item = session.get(AttentionItem, item_id)
    if item is None or item.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Attention item not found")

    try:
        new_state = AttentionState(payload.state)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid state: {payload.state}")

    if new_state == AttentionState.SNOOZED:
        if payload.snoozed_until is None:
            raise HTTPException(status_code=400, detail="snoozed_until is required when snoozing")
        item.snoozed_until = payload.snoozed_until
    else:
        item.snoozed_until = None

    item.state = new_state
    session.commit()
    session.refresh(item)
    return _to_out(item)
