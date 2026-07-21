import uuid

from pydantic import BaseModel, Field


class TeamCreate(BaseModel):
    """Full manual channel configuration (Phase 2o) - everything beyond
    `name` is optional so the minimal quick-create flow still works."""

    name: str = Field(..., min_length=1, max_length=200)
    # Phase 2y: the parent Group. Required - a Channel with no Group has no
    # place in the hierarchy and no workspace to derive authorization from.
    group_id: uuid.UUID
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=16)
    category: str | None = Field(default=None, max_length=100)  # legacy label, superseded by Group
    privacy: str = "public"  # public | invite_only | private
    member_user_ids: list[uuid.UUID] = []
    admin_user_ids: list[uuid.UUID] = []
    connection_ids: list[uuid.UUID] = []


class TeamUpdate(BaseModel):
    """Partial - omitted fields stay untouched; empty string clears a
    nullable field (description/icon/category)."""

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=16)
    category: str | None = Field(default=None, max_length=100)
    privacy: str | None = None


class TeamOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    group_id: uuid.UUID
    name: str
    slug: str
    member_count: int
    is_member: bool
    my_channel_role: str | None = None  # None if not a member; else "channel_admin"/"channel_member"
    description: str | None = None
    icon: str | None = None
    category: str | None = None
    privacy: str = "public"
    is_archived: bool = False

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
    role: str  # the caller's Workspace-level role
    channel_role: str  # the caller's Team-level role (channel_admin/channel_member)


class TeamMemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    channel_role: str


class TeamMemberRoleUpdate(BaseModel):
    channel_role: str


class TeamMemberAdd(BaseModel):
    """Admin adds an existing *workspace* member directly - the comment in
    join_team always promised "an admin adding you" as an entry path for
    non-public channels; this is that path. People outside the workspace
    still come in through invites, which is where account reuse and role
    assignment already live."""

    user_id: uuid.UUID
