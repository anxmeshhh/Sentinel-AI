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
