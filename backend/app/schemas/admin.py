import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AgentRunOut(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID | None
    connection_label: str | None
    status: str
    triggered_by: str
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: float | None
    node_errors: dict[str, str]
    error: str | None
    finding_count: int

    model_config = {"from_attributes": True}


class LogLineOut(BaseModel):
    timestamp: str | None = None
    level: str | None = None
    logger: str | None = None
    event: str | None = None
    run_id: str | None = None
    workspace_id: str | None = None
    agent: str | None = None
    connection_id: str | None = None
    raw: dict[str, Any]


class SystemStatsOut(BaseModel):
    connections: int
    signals: int
    findings: int
    briefs: int
    runs_total: int
    runs_success: int
    runs_partial: int
    runs_failed: int
    runs_running: int
