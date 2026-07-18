import uuid
from datetime import datetime

from pydantic import BaseModel


class MeetingOut(BaseModel):
    id: uuid.UUID
    title: str
    start: str | None
    end: str | None
    occurred_at: datetime
    attendee_count: int
    attendee_emails: list[str]
    status: str  # upcoming | past | cancelled
    calendar_url: str | None
    meet_url: str | None
