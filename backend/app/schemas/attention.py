import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AttentionItemOut(BaseModel):
    id: uuid.UUID
    type: str
    origin: str  # "detected" | "manual" - the UI renders these distinctly (✨ badge vs plain)
    state: str
    source_provider: str | None
    title: str
    why: str
    evidence_url: str | None
    priority: float
    due_at: datetime | None
    snoozed_until: datetime | None
    created_at: datetime


class AttentionStateUpdate(BaseModel):
    state: str  # new | done | snoozed | dismissed
    snoozed_until: datetime | None = None  # required when state == snoozed


class ManualReminderCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    why: str | None = Field(default=None, max_length=500)
    due_at: datetime | None = None
    evidence_url: str | None = Field(default=None, max_length=2000)
