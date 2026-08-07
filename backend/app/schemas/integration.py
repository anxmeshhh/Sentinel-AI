import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class ConnectTicketOut(BaseModel):
    ticket: str


class GitHubRepoOut(BaseModel):
    """A repository the connected token can actually read.

    Offered as a choice rather than typed by hand: a repo name entered by
    hand is a guess that fails silently at the first sync, while everything
    in this list is known to work before it is picked. `monitored` lets the
    picker show one Sentinel already watches instead of offering it again.
    """

    org: str
    repo: str
    full_name: str
    private: bool
    pushed_at: str | None = None
    monitored: bool = False
    connection_id: uuid.UUID | None = None


class GitHubRepositoryOut(BaseModel):
    """One repository Sentinel is monitoring, with its own health.

    The management view is per repository because the whole point of
    multi-repo is that they are independent - each carries its own sync
    timestamps, its own paused/revoked state, and its own signal count.
    """

    connection_id: uuid.UUID
    org: str
    repo: str
    full_name: str
    state: str
    paused: bool
    last_synced_at: datetime | None
    # When a sync last actually succeeded, which can lag last_synced_at when a
    # connection is failing - that gap is the point of showing both.
    last_success_at: datetime | None
    signal_count: int
    # How much this repository matters, set by a person. Drives whether a
    # critical-repo-gone-quiet situation fires for it.
    priority: str


class GitHubRepoSelect(BaseModel):
    org: str = Field(min_length=1, max_length=200)
    repo: str = Field(min_length=1, max_length=200)


class GitHubPrioritySet(BaseModel):
    priority: str = Field(pattern="^(critical|normal|low|archived|experimental)$")


class SlackChannelOut(BaseModel):
    """One public channel the connected workspace has. `is_member` is the
    operational fact: the bot can list any channel, but can only monitor one it
    has been invited to (that is what grants history access). `monitored` marks
    channels Sentinel already watches, so the picker can show them as such."""

    id: str
    name: str
    is_member: bool
    num_members: int | None = None
    topic: str = ""
    purpose: str = ""
    monitored: bool = False


class SlackChannelResourceOut(BaseModel):
    """One channel Sentinel is monitoring, with its own health - the exact
    shape of the GitHub repository view, because a channel is a resource the
    same way a repository is: independent sync state, paused/priority, and its
    own signal count."""

    connection_id: uuid.UUID
    channel_id: str
    name: str
    state: str
    paused: bool
    priority: str
    last_synced_at: datetime | None
    last_success_at: datetime | None
    signal_count: int
    # Last ingestion run's metrics: {ok, signals, messages_scanned, duration_ms,
    # at, error}. None until the channel has synced once.
    last_sync: dict | None = None


class SlackChannelAdd(BaseModel):
    channel_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)


class ResourcePrioritySet(BaseModel):
    """Provider-agnostic classification request - the same five levels every
    resource uses, so Slack and GitHub share one vocabulary."""

    priority: str = Field(pattern="^(critical|normal|low|archived|experimental)$")


class TeamsChannelOut(BaseModel):
    """One Teams channel the connected Microsoft account can see, for the picker.
    `monitored` marks the ones Sentinel already watches."""

    id: str
    name: str
    team_id: str
    team_name: str
    description: str = ""
    membership_type: str = "standard"
    monitored: bool = False


class TeamsChannelResourceOut(BaseModel):
    """One Teams channel Sentinel is monitoring - the same shape as the Slack and
    GitHub resource views, because a channel is a resource the same way a
    repository is: its own sync state, pause, priority and signal count.

    `messages_accessible` is the honest extra: Teams message reading sits behind
    a protected Graph permission, so a channel can be correctly monitored while
    producing no message-derived signals. Null means "not yet synced"."""

    connection_id: uuid.UUID
    channel_id: str
    team_id: str
    name: str
    state: str
    paused: bool
    priority: str
    last_synced_at: datetime | None
    signal_count: int = 0
    messages_accessible: bool | None = None


class TeamsChannelAdd(BaseModel):
    team_id: str = Field(min_length=1, max_length=200)
    team_name: str = Field(min_length=1, max_length=300)
    channel_id: str = Field(min_length=1, max_length=200)
    channel_name: str = Field(min_length=1, max_length=300)


class MicrosoftServiceOut(BaseModel):
    """One Microsoft service and what this account can do with it.

    `available` is a capability, not health: an unavailable service is one this
    account type does not include, which the UI explains rather than erroring on.
    `connected` is whether Sentinel actually holds a connection for it."""

    key: str
    label: str
    description: str
    available: bool
    status: str
    reason: str | None = None
    unlock: str | None = None
    connected: bool = False


class MicrosoftCapabilitiesOut(BaseModel):
    connected: bool
    account_type: str          # personal | business | enterprise | education | work_school | unknown | none
    account_type_label: str
    account: str | None = None
    tenant_name: str | None = None
    services: list[MicrosoftServiceOut] = []
