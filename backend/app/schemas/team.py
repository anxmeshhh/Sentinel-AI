import uuid

from pydantic import BaseModel, Field


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class TeamOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    member_count: int
    is_member: bool

    model_config = {"from_attributes": True}


class MyTeamOut(BaseModel):
    """A team the user actually belongs to, with its parent workspace
    attached - used by the cross-workspace "My Channels" dashboard section,
    which has no single active-workspace context to scope a query by.
    """

    id: uuid.UUID
    workspace_id: uuid.UUID
    workspace_name: str
    name: str
    slug: str
    member_count: int
    role: str
