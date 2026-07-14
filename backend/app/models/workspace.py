"""Workspace + Membership.

Phase 1 only ever exercises a single implicit Organization workspace with one
admin membership - but the shape supports Personal/Team/Organization and the
full RBAC role set from day one (see IA.md SS3, SS6) so Phase 1.5/2 are additive
rows, not a schema migration.
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPk


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


class Workspace(Base, UUIDPk, TimestampMixin):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    kind: Mapped[WorkspaceKind] = mapped_column(Enum(WorkspaceKind, name="workspace_kind"), nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class Membership(Base, UUIDPk, TimestampMixin):
    __tablename__ = "memberships"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    role: Mapped[Role] = mapped_column(Enum(Role, name="membership_role"), nullable=False)

    workspace: Mapped["Workspace"] = relationship(back_populates="memberships")
