import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_workspace_id
from app.models.signal import Signal
from app.schemas.calendar import CalendarEventOut
from app.services.calendar_query import CALENDAR_RANGES, list_calendar

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("", response_model=list[CalendarEventOut])
def get_calendar(
    range: str = "upcoming",
    limit: int = 30,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list[CalendarEventOut]:
    if range not in CALENDAR_RANGES:
        raise HTTPException(status_code=400, detail=f"Unknown range. Use one of: {sorted(CALENDAR_RANGES)}")
    signals = list_calendar(session, workspace_id, calendar_range=range, limit=min(limit, 100))
    return [_to_item(s) for s in signals]


def _to_item(s: Signal) -> CalendarEventOut:
    return CalendarEventOut(
        id=s.id,
        title=s.payload.get("title", "(no title)"),
        start=s.payload.get("start"),
        end=s.payload.get("end"),
        occurred_at=s.occurred_at,
        attendee_count=s.payload.get("attendee_count", 0),
        organizer=s.payload.get("organizer"),
        has_meeting_link=s.payload.get("has_meeting_link", False),
        url=s.payload.get("url"),
    )
