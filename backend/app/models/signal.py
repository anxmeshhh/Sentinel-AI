import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk, utcnow


class SignalType(str, enum.Enum):
    # One type per PR regardless of its current state (open/merged/closed) -
    # state lives inside `payload`. The idempotency key is
    # (connection_id, type, external_id): if state were encoded in `type`,
    # a PR transitioning from open -> merged would upsert a *second* row
    # instead of updating the first.
    PR = "pr"
    REVIEW_SUBMITTED = "review_submitted"
    COMMIT = "commit"
    ISSUE = "issue"
    CALENDAR_EVENT = "calendar_event"
    EMAIL = "email"
    # Drive files are never ingested from a real account (Drive is always
    # searched live - see google_drive_client.py). This type exists so the
    # seeded demo workspace can carry documents through the same Signal
    # pipeline everything else uses, keeping demo mode a data difference
    # rather than a second code path. Phase 2r.
    DRIVE_FILE = "drive_file"
    # Slack. Declared in Phase 0 (the provider knows what it will produce);
    # ingestion wires them in Phase 2. These are the raw operational substrate,
    # NOT findings: a channel had activity in a window, someone was mentioned,
    # or a message tripped the operational lexicon (blocked/urgent/asap/?).
    # The *findings* built on them (unanswered request, blocker) are
    # measurement-gated in Phase 4, deliberately not committed here.
    CHANNEL_ACTIVITY = "channel_activity"
    MENTION = "mention"
    FLAGGED_MESSAGE = "flagged_message"


class Signal(Base, UUIDPk, TimestampMixin):
    """An immutable, normalized fact ingested from an integration.

    Payload holds metadata only (titles, timestamps, authors, file paths,
    stats, review state) - never source code or diff bodies. See PRD SS7.
    """

    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("connection_id", "type", "external_id", name="uq_signal_connection_type_external_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("connections.id"), nullable=False, index=True)

    type: Mapped[SignalType] = mapped_column(Enum(SignalType, name="signal_type"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    connection: Mapped["Connection"] = relationship(back_populates="signals")
