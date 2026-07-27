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


class ProviderStatusOut(BaseModel):
    """One provider's line in the Sentinel-status card: is it healthy, and
    what did it actually contribute. `ok` is the trust signal; `error` carries
    the plain-language reason when it is False (auth expired, sync failing)."""

    provider: str
    label: str
    ok: bool
    state: str  # generic ConnectionState value - ready|syncing|error|token_revoked|needs_setup|paused
    resource_count: int
    signal_count: int  # 0 for live-query providers, which store nothing
    live: bool  # queried live at request time (Drive), never ingested into signals
    error: str | None  # human-readable reason when not ok
    last_synced_at: datetime | None


class SentinelStatusOut(BaseModel):
    """The first thing the Attention page shows: is Sentinel working, did it
    check everything, is anything wrong. Deterministic counts over the
    caller's own connections - no LLM, no provider calls. `healthy` is the
    single glance answer; `providers` and `errors` are the detail behind it."""

    healthy: bool
    provider_count: int
    resource_count: int
    signals_analysed: int
    findings_count: int  # open, Sentinel-detected items - the operational findings
    last_synced_at: datetime | None
    providers: list[ProviderStatusOut]
    errors: list[str]  # every provider error, flattened, for the status banner


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


# --- Channel Insights / Knowledge / Prepare (the three "soon" modules) ----

class InsightTypeCount(BaseModel):
    type: str
    label: str
    count: int


class InsightActor(BaseModel):
    actor: str
    count: int


class ChannelInsightsOut(BaseModel):
    no_connections: bool
    window_days: int
    total: int
    connection_labels: list[str] = []
    by_type: list[InsightTypeCount] = []
    top_actors: list[InsightActor] = []
    busiest_day: dict | None = None


class KnowledgeDocOut(BaseModel):
    id: str
    title: str
    url: str | None
    owner: str | None
    modified_at: datetime
    source_label: str


class ChannelKnowledgeOut(BaseModel):
    no_connections: bool
    documents: list[KnowledgeDocOut] = []
    connection_labels: list[str] = []


class UpcomingMeetingOut(BaseModel):
    signal_id: uuid.UUID
    external_id: str
    title: str
    start: str | None
    attendee_count: int
    url: str | None


class ChannelPrepareOut(BaseModel):
    no_connections: bool
    meetings: list[UpcomingMeetingOut] = []
