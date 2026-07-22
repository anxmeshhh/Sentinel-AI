"""Phase 2z: connections shared at a Class or Group level.

The tier between "one person's private connection" and "a single channel's
assignment": an admin authorizes a connection (and specific resources) once
at a Class or Group, and every Channel beneath it inherits that shared
context. Assign the class project repo once; all four of the Backend Team's
channels can use it, without four separate channel assignments.

Deliberately a *separate* table from ChannelConnection rather than a
generalization of it: the channel tier already works and is covered by
tests, and folding three levels into one polymorphic table would put that
behavior at risk for no gain. The resolver in channel_authorization.py is
where the three tiers are unioned; the storage stays simple.

Semantics are inheritance, not narrowing: anything assigned at a Class or
Group is shared with every Channel below it. A Channel seeing *less* than
its Class is not modeled - "shared" means shared. A channel that needs a
private slice assigns its own ChannelConnection instead.

Resources stay fail-closed exactly as at the channel tier: assigning a
Drive connection here grants no file until a resource_key is explicitly
allow-listed under it.
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPk


class SharedScope(str, enum.Enum):
    # WORKSPACE is the broadest tier (Phase 3a): an admin shares a connection
    # once for the whole workspace and every class/group/channel under it
    # inherits. Still an explicit act - connecting a service never shares it
    # anywhere by itself, which is what keeps the model fail-closed.
    WORKSPACE = "workspace"
    CLASS = "class"
    GROUP = "group"


class SharedConnection(Base, UUIDPk, TimestampMixin):
    __tablename__ = "shared_connections"
    # One assignment of a given connection per scope target. scope_id points
    # at a workspace_classes.id or workspace_groups.id depending on
    # scope_type - not a DB-level FK because it's polymorphic, so the routes
    # resolve and validate the target before writing (a bad scope_id simply
    # never matches during resolution and authorizes nothing).
    __table_args__ = (
        UniqueConstraint("scope_type", "scope_id", "connection_id", name="uq_shared_connection_scope_conn"),
    )

    scope_type: Mapped[SharedScope] = mapped_column(Enum(SharedScope, name="shared_scope"), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("connections.id"), nullable=False, index=True)
    added_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)

    resources: Mapped[list["SharedConnectionResource"]] = relationship(cascade="all, delete-orphan")


class SharedConnectionResource(Base, UUIDPk, TimestampMixin):
    """One allow-listed resource under a shared connection - same shape and
    fail-closed meaning as ChannelConnectionResource, one tier up."""

    __tablename__ = "shared_connection_resources"
    __table_args__ = (
        UniqueConstraint("shared_connection_id", "resource_key", name="uq_shared_connection_resource"),
    )

    shared_connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shared_connections.id"), nullable=False, index=True
    )
    resource_key: Mapped[str] = mapped_column(String(500), nullable=False)
    resource_label: Mapped[str] = mapped_column(String(300), nullable=False)


class ChannelConnectionExclusion(Base, UUIDPk, TimestampMixin):
    """Phase 3a: a Channel opting OUT of a connection it would inherit.

    The narrowing half of the model. Sharing at Workspace/Class/Group is what
    grants; this is the only thing that takes away, and it takes away for one
    channel only - "#announcements should not see GitHub" without unsharing
    GitHub from everyone else.

    Deny beats allow, unconditionally. An exclusion removes the connection
    from the channel's authorized set even if that same channel also has its
    own explicit ChannelConnection row. Two admins expressing opposite
    intentions is exactly the case where the safe reading has to win, and it
    keeps "is this channel authorized?" answerable without tracking which
    row was written last.

    This is deliberately NOT a second connection system: it stores no token,
    no resources, and grants nothing. It is a single subtractive fact.
    """

    __tablename__ = "channel_connection_exclusions"
    __table_args__ = (
        UniqueConstraint("team_id", "connection_id", name="uq_channel_connection_exclusion"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("teams.id"), nullable=False, index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("connections.id"), nullable=False, index=True)
    excluded_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
