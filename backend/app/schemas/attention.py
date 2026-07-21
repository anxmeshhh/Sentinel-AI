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


class ChannelBriefingOut(BaseModel):
    """Read-only by design - lifecycle actions live in the personal
    Attention hub (see services/channel_briefing.py's docstring)."""

    items: list[AttentionItemOut]
    narrative: str | None
    connection_labels: list[str]
    no_connections: bool

    # Phase 2x-B: required integrations the *caller* hasn't connected yet.
    # An empty briefing has two very different causes - "nothing needs your
    # attention" and "you never connected Gmail" - and only one of them is
    # the user's problem to fix. Reporting the second as the first is the
    # bug this field exists to prevent.
    blocking_providers: list[str] = []


class CalendarPlanOut(BaseModel):
    """A *proposal*, not a booking. The client shows this for confirmation
    and only then calls the existing execute endpoint - same
    confirm-before-write model as every other external action."""

    title: str
    start: datetime
    end: datetime
    action: str = "create_calendar_event"


class ManualReminderCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    why: str | None = Field(default=None, max_length=500)
    due_at: datetime | None = None
    evidence_url: str | None = Field(default=None, max_length=2000)


class ChannelFeedItemOut(BaseModel):
    """One normalized update from a connection this channel is authorized for."""

    id: uuid.UUID
    type: str
    type_label: str
    title: str
    actor: str | None
    provider: str
    source_label: str
    url: str | None
    occurred_at: datetime


class ChannelFeedOut(BaseModel):
    items: list[ChannelFeedItemOut]
    no_connections: bool
    connection_labels: list[str]
