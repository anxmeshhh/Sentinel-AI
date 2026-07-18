"""Phase 2m: per-Channel AI conversation history (spec section 13) - kept as
its own table, not reusing anything workspace-wide, since a Channel's AI
activity log is scoped strictly to that Channel and its members, never
shown across Channels.
"""

import uuid

from sqlalchemy import ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk


class ChannelAIHistoryEntry(Base, UUIDPk, TimestampMixin):
    __tablename__ = "channel_ai_history"

    team_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("teams.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    reply: Mapped[str] = mapped_column(Text, nullable=False)
