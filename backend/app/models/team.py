"""Team = Channel (IA.md v2 §2.4). Lives inside exactly one Workspace, not a
workspace kind of its own - this is what replaces v1's WorkspaceKind.TEAM.

Open-join by default: any Workspace member can join any Team in that
workspace without an invite (TeamMembership has no role of its own - access
level still comes from the Workspace-level Membership.role).
"""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk


class Team(Base, UUIDPk, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_team_workspace_slug"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)


class TeamMembership(Base, UUIDPk, TimestampMixin):
    __tablename__ = "team_memberships"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_membership_team_user"),)

    team_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("teams.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
