import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class InviteCreate(BaseModel):
    role: str = "employee"
    expires_in_hours: int | None = Field(default=None, gt=0)
    max_uses: int | None = Field(default=None, gt=0)


class InviteOut(BaseModel):
    token: str
    workspace_id: uuid.UUID
    team_id: uuid.UUID | None
    expires_at: datetime | None
    max_uses: int | None
    used_count: int

    model_config = {"from_attributes": True}


class InvitePreview(BaseModel):
    """Public - shown before the viewer decides to accept, so intentionally
    minimal (no member list, no internal ids beyond what's needed to accept)."""

    workspace_name: str
    team_name: str | None
    invited_by_name: str
    valid: bool
    reason_invalid: str | None = None


class InviteAcceptResult(BaseModel):
    workspace_id: uuid.UUID
    team_id: uuid.UUID | None
