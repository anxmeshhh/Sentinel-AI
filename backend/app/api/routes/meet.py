"""Meeting History for the Google Meet Workspace - see services/meet_query.py
for what this is (and isn't) built from.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_workspace_id
from app.models.signal import Signal
from app.schemas.meet import MeetingOut
from app.services.meet_query import MEETING_RANGES, list_meetings, meeting_status

router = APIRouter(prefix="/meet", tags=["meet"])


@router.get("/history", response_model=list[MeetingOut])
def get_meeting_history(
    range: str = "upcoming",
    search: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list[MeetingOut]:
    if range not in MEETING_RANGES:
        raise HTTPException(status_code=400, detail=f"Unknown range. Use one of: {sorted(MEETING_RANGES)}")
    signals = list_meetings(session, workspace_id, meeting_range=range, search=search, limit=min(limit, 100))
    return [_to_item(s) for s in signals]


def _to_item(s: Signal) -> MeetingOut:
    return MeetingOut(
        id=s.id,
        title=s.payload.get("title", "(no title)"),
        start=s.payload.get("start"),
        end=s.payload.get("end"),
        occurred_at=s.occurred_at,
        attendee_count=s.payload.get("attendee_count", 0),
        attendee_emails=s.payload.get("attendee_emails", []),
        status=meeting_status(s),
        calendar_url=s.payload.get("url"),
        meet_url=s.payload.get("meet_url"),
    )
