"""Invite links - workspace-scoped by default, team-scoped when `team_id` is
set (IA.md v2 §2.4: "a Team invite is just a Workspace invite with team_id
set"). One model covers both "join Acme Corporation" and "join Acme
Corporation, land directly in Backend Team" invite links.
"""

import secrets
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk
from app.models.workspace import Role


def _generate_token() -> str:
    return secrets.token_urlsafe(24)


class WorkspaceInvite(Base, UUIDPk, TimestampMixin):
    __tablename__ = "workspace_invites"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("teams.id"), nullable=True, index=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)

    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, default=_generate_token)
    role: Mapped[Role] = mapped_column(Enum(Role, name="membership_role"), default=Role.EMPLOYEE, nullable=False)

    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
