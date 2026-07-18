import uuid
from datetime import datetime

from pydantic import BaseModel


class MailItemOut(BaseModel):
    id: uuid.UUID
    subject: str
    sender: str
    to: str | None
    occurred_at: datetime
    is_starred: bool
    is_important: bool
    is_unread: bool
    is_spam: bool


class MailBodyOut(BaseModel):
    subject: str
    sender: str
    body_text: str | None
    fetched_live: bool = True


class MailAskRequest(BaseModel):
    question: str


class MailAskResponse(BaseModel):
    matched_filter: str | None
    matched_category: str | None
    items: list[MailItemOut]
    message: str | None = None
