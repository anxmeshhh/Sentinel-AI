import uuid

from sqlalchemy import JSON, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk


class Finding(Base, UUIDPk, TimestampMixin):
    """An opinion produced by one specialist agent for one run.

    Findings are immutable once written - a re-run produces new Finding rows,
    it never mutates old ones, so the brief history in the UI stays accurate
    to what was actually said at the time.
    """

    __tablename__ = "findings"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False, index=True)

    agent: Mapped[str] = mapped_column(String(50), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)

    severity: Mapped[float] = mapped_column(Float, nullable=False)  # 0..1
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0..1

    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[str] = mapped_column(Text, nullable=False)

    # Signal ids / external links (PR numbers, urls) that back this finding - the explainability trail.
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
