import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator


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

    @model_validator(mode="after")
    def _end_after_start(self) -> "CreateEventRequest":
        # Confirmed real: Google's Calendar API rejects end <= start with a
        # 400 that the old code let crash uncaught into a raw 500 - catch it
        # here instead, before ever making the request, with a message that
        # actually says what's wrong.
        if self.end <= self.start:
            raise ValueError("End time must be after start time")
        return self


class CreateEventOut(BaseModel):
    id: str
    title: str
    start: str | None
    end: str | None
    attendee_emails: list[str]
    meet_link: str | None
    url: str | None
