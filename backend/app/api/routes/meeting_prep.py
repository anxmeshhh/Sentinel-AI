"""Phase 2u: "Prepare Me" endpoints.

Two entry points, one implementation - a meeting can be reached either as
an attention item (the dashboard/Attention hub path) or directly as a
calendar Signal (the Meet/Calendar path). Neither is a new AI surface; both
call the same structured workflow in services/meeting_prep.py.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.models.attention_item import AttentionItem, AttentionType
from app.models.meeting_brief import MeetingBrief
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.schemas.meeting_prep import BriefSourceOut, MeetingBriefOut
from app.services.attention_engine import owns_attention_item
from app.services.meeting_prep import get_cached_brief, prepare_meeting

router = APIRouter(tags=["meeting-prep"])


def _to_out(brief: MeetingBrief, *, cached: bool) -> MeetingBriefOut:
    return MeetingBriefOut(
        id=brief.id, title=brief.title, narrative=brief.narrative,
        prep_points=list(brief.prep_points or []),
        sources=[BriefSourceOut(**s) for s in (brief.sources or [])],
        created_at=brief.created_at, cached=cached,
    )


def _resolve_event(session: Session, workspace_id: uuid.UUID, signal_id: uuid.UUID) -> Signal:
    event = session.get(Signal, signal_id)
    if event is None or event.workspace_id != workspace_id or event.type != SignalType.CALENDAR_EVENT:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return event


@router.post("/meetings/{signal_id}/prepare", response_model=MeetingBriefOut)
def prepare_from_signal(
    signal_id: uuid.UUID,
    refresh: bool = False,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> MeetingBriefOut:
    event = _resolve_event(session, workspace_id, signal_id)
    was_cached = not refresh and get_cached_brief(session, workspace_id, event.external_id) is not None
    brief = prepare_meeting(session, workspace_id, event, refresh=refresh)
    return _to_out(brief, cached=was_cached)


@router.post("/attention/{item_id}/prepare", response_model=MeetingBriefOut)
def prepare_from_attention_item(
    item_id: uuid.UUID,
    refresh: bool = False,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> MeetingBriefOut:
    """The main entry point: your next meeting is already sitting in the
    attention list, so preparing for it should be one click from there.

    Gated by the same ownership rule as the attention list itself: a brief
    built from someone else's meeting would disclose its title, attendees and
    related documents to a person the list never showed it to.
    """
    item = session.get(AttentionItem, item_id)
    if item is None or not owns_attention_item(session, item, workspace_id, user.id):
        raise HTTPException(status_code=404, detail="Attention item not found")
    if item.type != AttentionType.UPCOMING_MEETING:
        raise HTTPException(status_code=400, detail="Only meetings can be prepared for")

    # The detector builds this key as `meeting:{external_id}:{date}`, so the
    # external id is the middle segment.
    parts = item.dedupe_key.split(":")
    if len(parts) < 3:
        raise HTTPException(status_code=400, detail="This meeting can't be resolved")
    external_id = ":".join(parts[1:-1])

    event = session.execute(
        select(Signal).where(
            Signal.workspace_id == workspace_id,
            Signal.type == SignalType.CALENDAR_EVENT,
            Signal.external_id == external_id,
        )
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="The underlying meeting is no longer available")

    was_cached = not refresh and get_cached_brief(session, workspace_id, event.external_id) is not None
    brief = prepare_meeting(session, workspace_id, event, refresh=refresh)
    return _to_out(brief, cached=was_cached)
