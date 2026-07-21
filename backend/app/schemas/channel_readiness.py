import uuid

from pydantic import BaseModel, Field

from app.models.connection import Provider


class ChannelRequirementCreate(BaseModel):
    provider: Provider
    is_required: bool = True
    reason: str | None = Field(default=None, max_length=300)


class ChannelRequirementOut(BaseModel):
    id: uuid.UUID
    provider: str
    is_required: bool
    reason: str | None


class RequirementStatusOut(BaseModel):
    """One checklist row, as the acting member sees it.

    Carries no connection id and no token - only the provider, the derived
    state, and the account label this member connected themselves.
    """

    provider: str
    is_required: bool
    reason: str | None
    state: str
    account_label: str | None


class ChannelReadinessOut(BaseModel):
    team_id: uuid.UUID
    is_ready: bool
    blocking_providers: list[str]
    requirements: list[RequirementStatusOut]


class MemberReadinessOut(BaseModel):
    user_id: uuid.UUID
    name: str | None
    email: str
    role: str
    is_ready: bool
    requirements: list[dict]
