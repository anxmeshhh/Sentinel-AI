import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk, utcnow


class Brief(Base, UUIDPk, TimestampMixin):
    """The Executive Agent's synthesized output for one run - the one thing users read."""

    __tablename__ = "briefs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False, unique=True)

    generated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)

    # Ordered finding ids (as strings), most severe first. MySQL has no array
    # type, so this is a JSON list rather than Postgres ARRAY(String).
    top_finding_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Per-agent staleness/failure notes, e.g. {"engineering": "18h stale - last run failed"}.
    data_freshness: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
