"""Phase 2y: the two organizational levels between a Workspace and a Channel.

    Workspace  ->  Class  ->  Group  ->  Channel
    (tenant)      (domain)   (team)     (operational context)

A Class is a high-level domain ("Development", "Marketing"). A Group is a
team inside it ("Backend Team"). A Channel is one operational context inside
a Group ("#api-development"), and is still the `Team` model - renaming that
table would have touched every module that reads `team_id` for no behavioral
gain, so the *name* stayed and the *position* in the hierarchy changed.

## Why the model is `WorkspaceClass`

`class` is a Python keyword. `Class` as a bare name would be legal but reads
as a metaprogramming helper everywhere it's imported. The API and the UI both
say "class"; only the Python identifier is qualified.

## Why Channels keep a denormalized `workspace_id`

A Channel's workspace is reachable by `team -> group -> class -> workspace`,
so the column is redundant. It stays because ~10 modules
(`require_channel_role`, `channel_briefing`, `channel_readiness`, connection
assignment) already authorize against `team.workspace_id`, and rewriting all
of them into three-table joins would risk the authorization layer to remove
one column.

The cost of denormalization is that it can *disagree* with the path - a
Channel could claim workspace A while its Group's Class belongs to workspace
B, and every one of those authorization checks would then be asking the wrong
question. So the write path derives `workspace_id` from the parent Group
rather than accepting it from a caller, and
`test_hierarchy_isolation.py` pins that the two can never diverge.
"""

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk


class WorkspaceClass(Base, UUIDPk, TimestampMixin):
    """A high-level domain inside one Workspace ("Development", "Sales")."""

    __tablename__ = "workspace_classes"
    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_class_workspace_slug"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Display order within the workspace sidebar. Explicit rather than
    # alphabetical so "Development" can sit above "Admin" when that's how
    # the organization actually thinks.
    position: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)


class Group(Base, UUIDPk, TimestampMixin):
    """A team inside exactly one Class ("Backend Team").

    Slug uniqueness is scoped to the Class, not the Workspace: two Classes
    may each legitimately contain a "Platform" group, and forcing globally
    unique names across a whole organization would be a naming tax with no
    security value.
    """

    __tablename__ = "workspace_groups"
    __table_args__ = (UniqueConstraint("class_id", "slug", name="uq_group_class_slug"),)

    class_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspace_classes.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    position: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
