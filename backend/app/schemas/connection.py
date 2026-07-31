import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ConnectionCreate(BaseModel):
    org: str = Field(..., examples=["northwind"])
    repo: str = Field(..., examples=["checkout-service"])
    github_token: str = Field(
        ...,
        description="GitHub PAT with repo read scope. Encrypted at rest; never returned by the API.",
    )


class ConnectionOut(BaseModel):
    id: uuid.UUID
    provider: str
    org: str
    repo: str
    last_synced_at: datetime | None
    # Real health, so the UI never shows "Connected" for a revoked or failing
    # connection. One of: ready | live | syncing | error | token_revoked |
    # paused | needs_setup (see services/connection_state.py).
    state: str | None = None

    model_config = {"from_attributes": True}
