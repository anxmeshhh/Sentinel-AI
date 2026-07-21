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
