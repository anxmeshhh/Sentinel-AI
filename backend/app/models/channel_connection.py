"""Phase 2l: lets a Group Connection be assigned to specific Channels, with
resource-level allow-listing on top - the part of the "Discord-Inspired
Groups & Channels" spec that genuinely doesn't exist anywhere yet (Connection
today is 100% workspace-wide, see connection.py's docstring).

Deliberately fail-closed, not fail-open, matching the spec's explicit
requirement ("adding a Connection does not automatically give the Channel
access to everything available through that Connection"): assigning a
Connection to a Channel grants zero resource access on its own. A resource
(a GitHub repo, a Drive folder/file, a Jira project) is only usable by that
Channel's AI/members once an admin explicitly adds an allow-list row for it.
No separate "block" entry type exists because default-deny already means
"absent = blocked" - there's nothing a block row would add.
"""

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPk


class ChannelConnection(Base, UUIDPk, TimestampMixin):
    __tablename__ = "channel_connections"
    __table_args__ = (UniqueConstraint("team_id", "connection_id", name="uq_channel_connection"),)

    team_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("teams.id"), nullable=False, index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("connections.id"), nullable=False, index=True)
    added_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)

    resources: Mapped[list["ChannelConnectionResource"]] = relationship(cascade="all, delete-orphan")


class ChannelConnectionResource(Base, UUIDPk, TimestampMixin):
    """One allow-listed resource within a Channel's assigned Connection -
    e.g. resource_key="northwind/checkout-service" for a GitHub repo, or a
    Drive file/folder id for Google Drive. `resource_label` is just a
    human-readable display string (a repo name, a folder name) - never
    used for the actual permission check, which always goes by
    `resource_key`.
    """

    __tablename__ = "channel_connection_resources"
    __table_args__ = (UniqueConstraint("channel_connection_id", "resource_key", name="uq_channel_connection_resource"),)

    channel_connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("channel_connections.id"), nullable=False, index=True
    )
    resource_key: Mapped[str] = mapped_column(String(500), nullable=False)
    resource_label: Mapped[str] = mapped_column(String(300), nullable=False)
