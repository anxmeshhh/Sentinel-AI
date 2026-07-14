import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Enum, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class RunStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"  # some agent nodes failed, others produced output
    FAILED = "failed"


class TriggeredBy(str, enum.Enum):
    SCHEDULE = "schedule"
    MANUAL = "manual"


class AgentRun(Base, UUIDPk, TimestampMixin):
    """One execution of the LangGraph pipeline for one connection.

    This is the correlation id (`run_id`) threaded through logs, traces, and
    every Finding/Brief produced by the run - see ARCHITECTURE.md and the
    observability notes in chat: run_id + workspace_id are the two ids the
    whole security/observability story hangs off.
    """

    __tablename__ = "agent_runs"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("connections.id"), nullable=True, index=True)

    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus, name="run_status"), default=RunStatus.RUNNING, nullable=False)
    triggered_by: Mapped[TriggeredBy] = mapped_column(Enum(TriggeredBy, name="run_triggered_by"), nullable=False)

    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Which agent nodes failed and why - drives the "partial failure is first-class" behavior.
    node_errors: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
