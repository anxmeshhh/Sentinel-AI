"""Operator observability surface - agent run history, system counts, and a
tail of the structured log file.

This is NOT part of the customer-facing IA (see IA.md) - it's for whoever
operates the Sentinel instance itself. Phase 1 has no auth, so it's wide
open; before Phase 2's RBAC ships, this must be gated to the Super Admin
role only (IA.md §3) - it is not safe to leave reachable by every workspace
member once real multi-tenant auth exists.
"""

import json
import uuid
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_workspace_id
from app.core.logging import LOG_FILE_PATH
from app.models.agent_run import AgentRun, RunStatus
from app.models.brief import Brief
from app.models.connection import Connection
from app.models.finding import Finding
from app.models.signal import Signal
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.findings import FindingRepository
from app.schemas.admin import AgentRunOut, LogLineOut, SystemStatsOut
from app.schemas.finding import FindingOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/runs", response_model=list[AgentRunOut])
def list_runs(
    limit: int = 50,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list[AgentRunOut]:
    runs = AgentRunRepository(session, workspace_id).list_recent(limit=limit)
    connections = {c.id: c for c in session.execute(select(Connection)).scalars().all()}

    out = []
    for run in runs:
        finding_count = session.execute(
            select(func.count()).select_from(Finding).where(Finding.run_id == run.id)
        ).scalar_one()
        connection = connections.get(run.connection_id) if run.connection_id else None
        duration = (run.finished_at - run.started_at).total_seconds() if run.finished_at else None
        out.append(
            AgentRunOut(
                id=run.id,
                connection_id=run.connection_id,
                connection_label=connection.full_name if connection else None,
                status=run.status.value,
                triggered_by=run.triggered_by.value,
                started_at=run.started_at,
                finished_at=run.finished_at,
                duration_seconds=duration,
                node_errors=run.node_errors,
                error=run.error,
                finding_count=finding_count,
            )
        )
    return out


@router.get("/runs/{run_id}/findings", response_model=list[FindingOut])
def run_findings(
    run_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list[FindingOut]:
    return FindingRepository(session, workspace_id).for_run(run_id)


@router.get("/logs", response_model=list[LogLineOut])
def tail_logs(limit: int = 200) -> list[LogLineOut]:
    path = Path(LOG_FILE_PATH)
    if not path.exists():
        return []

    # Simple tail: fine at Phase-1 log volume. Revisit if the file grows large
    # enough that reading it whole becomes noticeably slow.
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    recent = lines[-limit:]

    out = []
    for line in reversed(recent):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(
            LogLineOut(
                timestamp=data.get("timestamp"),
                level=data.get("level"),
                logger=data.get("logger"),
                event=data.get("event"),
                run_id=data.get("run_id"),
                workspace_id=data.get("workspace_id"),
                agent=data.get("agent"),
                connection_id=data.get("connection_id"),
                raw=data,
            )
        )
    return out


@router.get("/stats", response_model=SystemStatsOut)
def system_stats(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> SystemStatsOut:
    def count(model, *filters) -> int:
        stmt = select(func.count()).select_from(model).where(model.workspace_id == workspace_id, *filters)
        return session.execute(stmt).scalar_one()

    run_statuses = Counter(
        session.execute(
            select(AgentRun.status).where(AgentRun.workspace_id == workspace_id)
        ).scalars().all()
    )

    return SystemStatsOut(
        connections=count(Connection),
        signals=count(Signal),
        findings=count(Finding),
        briefs=count(Brief),
        runs_total=sum(run_statuses.values()),
        runs_success=run_statuses.get(RunStatus.SUCCESS, 0),
        runs_partial=run_statuses.get(RunStatus.PARTIAL, 0),
        runs_failed=run_statuses.get(RunStatus.FAILED, 0),
        runs_running=run_statuses.get(RunStatus.RUNNING, 0),
    )
