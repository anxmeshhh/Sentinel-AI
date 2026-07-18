import uuid

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk


class EmailSummary(Base, UUIDPk, TimestampMixin):
    """A cached AI summary of one email, keyed by Gmail's own message id (not
    a Signal id - since search_emails does a live whole-mailbox search, a
    summarized email may not correspond to any locally-ingested Signal row
    at all). Generated once, on demand, the first time a user asks for a
    given email's summary; every subsequent open reuses this row instead of
    re-fetching the body and re-calling the LLM - the token-efficiency
    requirement behind this table existing at all.
    """

    __tablename__ = "email_summaries"
    __table_args__ = (UniqueConstraint("workspace_id", "message_id", name="uq_email_summary_workspace_message"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    message_id: Mapped[str] = mapped_column(String(200), nullable=False)

    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    sender: Mapped[str] = mapped_column(String(500), nullable=False)

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    action_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
