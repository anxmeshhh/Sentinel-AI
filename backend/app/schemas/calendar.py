import uuid
from datetime import datetime

from pydantic import BaseModel


class CalendarEventOut(BaseModel):
    id: uuid.UUID
    title: str
    start: str | None
    end: str | None
    occurred_at: datetime
    attendee_count: int
    attendee_emails: list[str]
    organizer: str | None
    has_meeting_link: bool
    meet_url: str | None
    status: str
    url: str | None


class CreateEventRequest(BaseModel):
    title: str
    start: datetime
    end: datetime
    attendee_emails: list[str] = []
    create_meet_link: bool = False


class CreateEventOut(BaseModel):
    id: str
    title: str
    start: str | None
    end: str | None
    attendee_emails: list[str]
    meet_link: str | None
    url: str | None
