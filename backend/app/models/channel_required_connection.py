"""Phase 2x-B: what a Channel *needs*, declared by an admin.

This is deliberately not the same thing as `ChannelConnection`. The two
answer different questions and must not be collapsed:

- `ChannelConnection` = "this specific connection row (someone's authorized
  account) is assigned to this channel". It points at a token.
- `ChannelRequiredConnection` = "this channel needs Gmail". It points at a
  *provider*, never at an account or a token.

The distinction is the whole point of the phase. An admin configuring a
channel is stating a requirement about a category of tool; each member then
satisfies that requirement with **their own** account. An admin who could
declare the requirement *and* supply the account would be handing their own
mailbox to the channel - which is exactly the leak the per-user ownership
change in Phase A closed.

So there is no `connection_id` on this table, and there is no route that
would let an admin create one on a member's behalf.
"""

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk
from app.models.connection import Provider


class ChannelRequiredConnection(Base, UUIDPk, TimestampMixin):
    __tablename__ = "channel_required_connections"
    __table_args__ = (UniqueConstraint("team_id", "provider", name="uq_channel_required_connection"),)

    team_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("teams.id"), nullable=False, index=True)
    provider: Mapped[Provider] = mapped_column(Enum(Provider, name="connection_provider"), nullable=False)

    # Optional requirements are shown in the checklist but never block. A
    # channel that marks everything required just to be thorough would train
    # members to ignore the checklist, so the distinction has to be real.
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # The admin's own words for why - shown to the member on the checklist.
    # "Connect Gmail" is a demand; "Connect Gmail so client replies show up
    # here" is a reason. Members are being asked for mailbox access; they are
    # owed the second one.
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    added_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
