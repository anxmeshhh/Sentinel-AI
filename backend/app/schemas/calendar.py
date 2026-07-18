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
    organizer: str | None
    has_meeting_link: bool
    url: str | None
