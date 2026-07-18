import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_workspace_id
from app.integrations.google_auth import get_valid_access_token
from app.integrations.google_calendar_client import GoogleCalendarClient
from app.models.connection import Provider
from app.models.signal import Signal
from app.repositories.connections import ConnectionRepository
from app.schemas.calendar import CalendarEventOut, CreateEventOut, CreateEventRequest
from app.schemas.holiday import HolidayOut
from app.services.calendar_query import CALENDAR_RANGES, list_calendar, list_calendar_month, list_calendar_range
from app.services.holiday_query import list_indian_holidays
from app.services.ingestion import ingest_connection

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("", response_model=list[CalendarEventOut])
def get_calendar(
    range: str = "upcoming",
    since: str | None = None,
    until: str | None = None,
    limit: int = 30,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list[CalendarEventOut]:
    """Either an explicit since/until date range (used by the Week/Day
    views), or the simple upcoming/past split (used by Agenda)."""
    if since or until:
        try:
            since_dt = datetime.fromisoformat(since) if since else datetime.min
            until_dt = datetime.fromisoformat(until) if until else datetime.max
        except ValueError:
            raise HTTPException(status_code=400, detail="since/until must be ISO datetimes")
        signals = list_calendar_range(session, workspace_id, since=since_dt, until=until_dt, limit=min(limit, 100))
        return [_to_item(s) for s in signals]

    if range not in CALENDAR_RANGES:
        raise HTTPException(status_code=400, detail=f"Unknown range. Use one of: {sorted(CALENDAR_RANGES)}")
    signals = list_calendar(session, workspace_id, calendar_range=range, limit=min(limit, 100))
    return [_to_item(s) for s in signals]


@router.get("/month", response_model=list[CalendarEventOut])
def get_calendar_month(
    year: int,
    month: int,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list[CalendarEventOut]:
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be 1-12")
    signals = list_calendar_month(session, workspace_id, year=year, month=month)
    return [_to_item(s) for s in signals]


@router.get("/holidays", response_model=list[HolidayOut])
def get_holidays(
    year: int,
    month: int | None = None,
    state: str | None = None,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list[HolidayOut]:
    """Live from Google's public Indian holiday calendar - see
    services/holiday_query.py's docstring. month omitted = the whole year."""
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be 1-12")

    if month is not None:
        since = datetime(year, month, 1)
        until = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    else:
        since = datetime(year, 1, 1)
        until = datetime(year + 1, 1, 1)

    holidays = list_indian_holidays(session, workspace_id, since=since, until=until, state=state)
    return [HolidayOut(**h) for h in holidays]


@router.post("/events", response_model=CreateEventOut, status_code=201)
def create_event(
    payload: CreateEventRequest,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> CreateEventOut:
    """Direct, immediate creation - no confirm-plan step, unlike the AI
    Command's create_calendar_event tool. A manual form submission the user
    filled out themselves already *is* the confirmation; the plan-preview
    step exists specifically for actions an LLM inferred, not ones a human
    typed into a form with their own hands.
    """
    connection = ConnectionRepository(session, workspace_id).get_by_provider(Provider.GOOGLE_CALENDAR)
    if connection is None:
        raise HTTPException(status_code=404, detail="Google Calendar is not connected")

    access_token = get_valid_access_token(session, connection)
    try:
        with GoogleCalendarClient(access_token) as client:
            result = client.create_event(
                title=payload.title,
                start=payload.start,
                end=payload.end,
                attendee_emails=payload.attendee_emails,
                create_meet_link=payload.create_meet_link,
            )
    except httpx.HTTPStatusError as exc:
        # Confirmed real: previously uncaught, so any rejection from Google
        # (bad attendee address, disabled conferencing, etc.) crashed as a
        # raw 500 with no useful message - surface Google's own reason
        # instead.
        try:
            reason = exc.response.json().get("error", {}).get("message", exc.response.text[:200])
        except ValueError:
            reason = exc.response.text[:200]
        raise HTTPException(status_code=exc.response.status_code, detail=f"Google Calendar rejected this: {reason}") from exc

    # Without this, the new event wouldn't appear in Month/Week/Day/Agenda
    # until the next scheduled poll (default every 6h, see
    # ingestion_poll_interval_seconds) - confirmed as a real gap: a user
    # created an event and couldn't see it anywhere in the app afterward.
    ingest_connection(session, connection)

    return CreateEventOut(**result)


def _to_item(s: Signal) -> CalendarEventOut:
    return CalendarEventOut(
        id=s.id,
        title=s.payload.get("title", "(no title)"),
        start=s.payload.get("start"),
        end=s.payload.get("end"),
        occurred_at=s.occurred_at,
        attendee_count=s.payload.get("attendee_count", 0),
        attendee_emails=s.payload.get("attendee_emails", []),
        organizer=s.payload.get("organizer"),
        has_meeting_link=s.payload.get("has_meeting_link", False),
        meet_url=s.payload.get("meet_url"),
        status=s.payload.get("status", "confirmed"),
        url=s.payload.get("url"),
    )
