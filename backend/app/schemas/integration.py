from pydantic import BaseModel, Field


class ConnectTicketOut(BaseModel):
    ticket: str


class GitHubRepoOut(BaseModel):
    """A repository the connected token can actually read.

    Offered as a choice rather than typed by hand: a repo name entered by
    hand is a guess that fails silently at the first sync, while everything
    in this list is known to work before it is picked.
    """

    org: str
    repo: str
    full_name: str
    private: bool
    pushed_at: str | None = None


class GitHubRepoSelect(BaseModel):
    org: str = Field(min_length=1, max_length=200)
    repo: str = Field(min_length=1, max_length=200)
