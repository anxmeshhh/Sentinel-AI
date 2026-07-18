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
