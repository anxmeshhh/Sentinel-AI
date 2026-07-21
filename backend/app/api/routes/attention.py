"""Phase 2p: the Attention API - Sentinel's unified "what needs my
attention" feed. Detection itself lives in services/attention_engine.py
(deterministic, no LLM); these routes expose the list, the lifecycle
actions (done/snooze/dismiss), manual reminders, and an on-demand refresh.
"""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.connection import Connection
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.services.mail_signals import noise_reason, sender_counts
from app.schemas.attention import AttentionItemOut, AttentionStateUpdate, CalendarPlanOut, ManualReminderCreate
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
) -> list[AttentionItemOut]:
    items = list_attention(session, workspace_id, states=_parse_states(state))
    return [_to_out(i) for i in items]


@router.get("/context")
def attention_context(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> dict:
    """Why the attention list looks the way it does.

    An empty feed has three completely different causes - nothing is
    connected, something is connected but hasn't synced yet, or everything
    synced and genuinely nothing needs you - and they call for three
    different responses from the user. Showing one blank message for all
    three reads as "broken", which is exactly the impression an attention
    product cannot afford.

    Pure counts, no LLM, no provider calls.
    """
    connections = session.execute(
        select(Connection).where(Connection.workspace_id == workspace_id)
    ).scalars().all()
    synced = [c for c in connections if c.last_synced_at is not None]
    last_synced = max((c.last_synced_at for c in synced), default=None)

    emails = session.execute(
        select(Signal).where(Signal.workspace_id == workspace_id, Signal.type == SignalType.EMAIL)
    ).scalars().all()

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
) -> list[AttentionItemOut]:
    """On-demand re-detection - also runs automatically after every sync
    cycle, so this exists for the "refresh" button, not as the primary path."""
    items = refresh_attention(session, workspace_id)
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
