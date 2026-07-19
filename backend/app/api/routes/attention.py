"""Phase 2p: the Attention API - Sentinel's unified "what needs my
attention" feed. Detection itself lives in services/attention_engine.py
(deterministic, no LLM); these routes expose the list, the lifecycle
actions (done/snooze/dismiss), manual reminders, and an on-demand refresh.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.user import User
from app.schemas.attention import AttentionItemOut, AttentionStateUpdate, ManualReminderCreate
from app.services.attention_engine import list_attention, refresh_attention

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
