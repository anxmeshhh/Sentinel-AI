import uuid

from pydantic import BaseModel, Field


class ClassCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=16)


class ClassUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=16)
    position: int | None = None


class ClassOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    icon: str | None
    position: int
    group_count: int


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=16)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=16)
    position: int | None = None


class GroupOut(BaseModel):
    id: uuid.UUID
    class_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    icon: str | None
    position: int
    channel_count: int


class TreeChannelOut(BaseModel):
    """A Channel as it appears in the navigation tree - identity and enough
    state to render it, not the full channel payload."""

    id: uuid.UUID
    name: str
    slug: str
    icon: str | None
    privacy: str
    is_member: bool
    member_count: int


class TreeGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    icon: str | None
    description: str | None
    channels: list[TreeChannelOut]


class TreeClassOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    icon: str | None
    description: str | None
    groups: list[TreeGroupOut]


class ChannelPathOut(BaseModel):
    """Breadcrumb: Workspace / Class / Group / #Channel."""

    workspace_id: uuid.UUID
    workspace_name: str
    class_id: uuid.UUID
    class_name: str
    group_id: uuid.UUID
    group_name: str
    channel_id: uuid.UUID
    channel_name: str
