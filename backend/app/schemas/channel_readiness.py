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

    `provided_by` names the tier that already shares this provider with the
    channel ("workspace"/"class"/"group"/"channel"), or None. It is a tier
    name, never an account or a connection id: knowing the requirement is
    already covered tells a member what they need to do, while naming whose
    account covers it would not.
    """

    provider: str
    is_required: bool
    reason: str | None
    state: str
    account_label: str | None
    provided_by: str | None = None


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
