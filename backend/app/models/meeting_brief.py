"""Phase 2u: a cached "Prepare Me" brief for one meeting.

Same reasoning as EmailSummary: the expensive part (retrieval + one LLM
synthesis) runs once, and every subsequent open of the same meeting's brief
costs zero tokens. Briefs don't change minute-to-minute, so caching is the
single biggest cost control in this workflow.

Keyed by the meeting's external calendar id rather than a Signal id, so a
re-sync that replaces Signal rows doesn't orphan the brief.
"""

import uuid

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk


class MeetingBrief(Base, UUIDPk, TimestampMixin):
    __tablename__ = "meeting_briefs"
    __table_args__ = (UniqueConstraint("workspace_id", "event_external_id", name="uq_meeting_brief_workspace_event"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    event_external_id: Mapped[str] = mapped_column(String(300), nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    prep_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Every source the brief drew on, as {kind, label, url} - what makes a
    # claim traceable rather than something the user has to take on faith.
    sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
