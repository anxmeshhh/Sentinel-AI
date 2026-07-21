"""Team = Channel (IA.md v2 §2.4). Lives inside exactly one Workspace, not a
workspace kind of its own - this is what replaces v1's WorkspaceKind.TEAM.

Open-join by default: any Workspace member can join any Team in that
workspace without an invite. TeamMembership now carries its own ChannelRole
(Phase 3a) - access to channel-scoped admin actions (assigning Connections,
managing resource permissions, promoting/removing members) is governed by
this, independently of the caller's Workspace-level Membership.role, since a
person can be a Channel Admin of #development while just a plain member of
#marketing in the same Workspace.
"""

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk


class ChannelRole(str, enum.Enum):
    CHANNEL_ADMIN = "channel_admin"
    CHANNEL_MEMBER = "channel_member"


class ChannelPrivacy(str, enum.Enum):
    """Phase 2o. PUBLIC keeps Phase 2a's open-join behavior (any workspace
    member sees + joins freely). INVITE_ONLY stays visible in the channel
    list but the join route rejects - entry is only via an accepted invite.
    PRIVATE is additionally hidden from non-members entirely (list and
    direct lookup both 404, same don't-confirm-existence convention as the
    rest of deps.py) - workspace admins excepted, since a Group Owner/Admin
    has full control over every Channel.
    """

    PUBLIC = "public"
    INVITE_ONLY = "invite_only"
    PRIVATE = "private"


class Team(Base, UUIDPk, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_team_workspace_slug"),)

    # Denormalized from group -> class -> workspace. Kept because the whole
    # authorization layer already reads it; never accepted from a caller,
    # always derived from the parent Group on write. See models/hierarchy.py
    # for the full reasoning and the test that pins the two can't diverge.
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)

    # Phase 2y: a Channel lives inside exactly one Group. Nullable only so
    # the backfill migration can run in two steps; every write path requires
    # it, and the column is NOT NULL in the database.
    group_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspace_groups.id"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(16), nullable=True)  # an emoji, not an image
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)  # free-form grouping label ("Teams", "Projects")
    privacy: Mapped[ChannelPrivacy] = mapped_column(
        Enum(ChannelPrivacy, name="channel_privacy"), nullable=False,
        default=ChannelPrivacy.PUBLIC, server_default=ChannelPrivacy.PUBLIC.name,
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")


class TeamMembership(Base, UUIDPk, TimestampMixin):
    __tablename__ = "team_memberships"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_membership_team_user"),)

    team_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("teams.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[ChannelRole] = mapped_column(
        # server_default must be the enum member's *name* ('CHANNEL_MEMBER'),
        # not its .value ('channel_member') - SQLAlchemy's Enum type stores
        # member names in the DB column by default, matching this
        # codebase's existing membership_role/workspace_kind columns.
        Enum(ChannelRole, name="channel_role"), nullable=False, default=ChannelRole.CHANNEL_MEMBER, server_default=ChannelRole.CHANNEL_MEMBER.name
    )
