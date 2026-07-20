"""Workspace + Membership.

Phase 1 only ever exercised a single implicit Organization workspace with one
admin membership. Phase 1.5 adds a second, real Personal Workspace per user -
the shape has supported Personal/Team/Organization and the full RBAC role set
from day one (see IA.md SS3, SS6), so this is an additive row via
core/bootstrap.py, not a schema migration.
"""

import enum
import uuid
from datetime import datetime  # noqa: TC003 - used in Mapped annotation

from sqlalchemy import Boolean, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class WorkspaceKind(str, enum.Enum):
    PERSONAL = "personal"
    TEAM = "team"
    ORGANIZATION = "organization"


class Role(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN = "org_admin"
    TEAM_MANAGER = "team_manager"
    EMPLOYEE = "employee"
    GUEST = "guest"


# Declaration order above is rank order (most to least privileged) - used
# wherever an action must check a role isn't more privileged than another
# (e.g. an invite can't grant a role above the inviter's own, Phase 3a).
ROLE_RANK = {role: i for i, role in enumerate(Role)}


class Workspace(Base, UUIDPk, TimestampMixin):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    kind: Mapped[WorkspaceKind] = mapped_column(Enum(WorkspaceKind, name="workspace_kind"), nullable=False)

    # Phase 2r: a seeded "Explore Sentinel" workspace. Its Connections hold
    # no real credentials, so every integration path must read from seeded
    # Signals instead of calling a provider API - see services/demo_data.py
    # and the orchestrator's demo branches. Flagged on the Workspace (not
    # inferred from the connection) so the check is one cheap lookup.
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    memberships: Mapped[list["Membership"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class Membership(Base, UUIDPk, TimestampMixin):
    __tablename__ = "memberships"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[Role] = mapped_column(Enum(Role, name="membership_role"), nullable=False)

    # Phase 2q: when this user last looked at this workspace's dashboard -
    # the anchor for "Catch Me Up" (what changed since you were last here).
    # Per-membership, not per-user, because the same person can be away
    # from one workspace while active daily in another.
    last_seen_at: Mapped["datetime | None"] = mapped_column(UTCDateTime, nullable=True)

    workspace: Mapped["Workspace"] = relationship(back_populates="memberships")
