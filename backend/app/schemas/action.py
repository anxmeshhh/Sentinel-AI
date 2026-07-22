import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ActionCatalogEntry(BaseModel):
    """What Sentinel is allowed to do - including what it is not allowed to
    do yet, with the reason, so the boundary is legible."""

    key: str
    label: str
    risk: str
    scopes: list[str]
    external: bool
    needs_approval: bool
    available: bool
    unavailable_reason: str | None
    requires_channel_admin: bool


class ActionOut(BaseModel):
    id: uuid.UUID
    action_type: str
    risk: str
    status: str

    params: dict
    # Exactly what the user was shown before approving - stored, not
    # re-rendered, so the record proves what they agreed to.
    preview: dict
    reason: str | None

    source_kind: str | None
    source_id: uuid.UUID | None

    requested_by_user_id: uuid.UUID
    approved_by_user_id: uuid.UUID | None
    approved_at: datetime | None
    executed_at: datetime | None

    result: dict
    error: str | None
    # How the outcome was confirmed. A success with no verification is not
    # reported as a success.
    verification: str | None
    created_at: datetime


class ActionCreate(BaseModel):
    action_type: str = Field(max_length=80)
    params: dict = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=1000)
    source_kind: str | None = Field(default=None, max_length=40)
    source_id: uuid.UUID | None = None
