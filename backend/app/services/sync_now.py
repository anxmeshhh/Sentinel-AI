"""'Sync Now' - a real, synchronous full refresh of one user's own world.

The scheduled path (app/workers/tasks.py:ingest_connection) already IS the
full pipeline - ingest -> attention -> proactive -> Intelligence Core
(situations/reasoning/memory/decisions) -> commitments -> goals - just async,
one connection at a time via Celery, with no way for a caller to know when
it's done.

`run_full_sync` calls the exact same functions, in the exact same order, for
every one of the caller's own connections in the current workspace - but
in-process, so the caller (the /sync route) gets a real completion signal:
the function returning. No polling, no new status table, no fake timers.

The one deliberate difference from the Celery task: the workspace-level
refreshes (attention/proactive/intelligence/commitments/goals) run ONCE after
every connection has ingested, not once per connection - safe because each is
already a full, idempotent recomputation over current data, not an
incremental delta, so running it N times or once produces the identical end
state. Redundant, not different.

Deliberately NOT included: app.services.agent_orchestration.run_agents_for_connection,
the separate LangGraph agent/Brief pipeline - it is outside Signals -> Findings
-> Entities -> Situations -> Context -> Reasoning -> Memory -> Decisions, and
can be slow. It stays dispatched async, exactly as the scheduled path already
does for it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection import Connection, Provider
from app.services import ingestion
from app.services.attention_engine import refresh_attention
from app.services.commitments import refresh_commitments_for_workspace
from app.services.goals import affected_scope_keys, reassess_goals_for_workspace
from app.services.proactive import refresh_proactive_for_workspace
from app.services.situation_engine import refresh_intelligence_for_workspace

logger = structlog.get_logger("sentinel.sync")


@dataclass
class SyncOutcome:
    status: str  # "success" | "partial" | "failed" | "no_connections"
    connections_checked: int
    connections_failed: int
    signals_ingested: int
    synced_at: datetime
    errors: list[str] = field(default_factory=list)


def run_full_sync(
    session: Session,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    providers: tuple[Provider, ...] | None = None,
) -> SyncOutcome:
    """Sync this user's own connections in this workspace, then rebuild
    everything downstream of fresh signals. Commits on completion - callers
    do not need to commit separately.

    `providers`, when given, narrows which connections are pulled - e.g. a
    provider page's own Sync Now syncing just that provider rather than the
    caller's whole world. The downstream pipeline still runs for the whole
    workspace either way: each stage is already a full recomputation over
    current data, not an incremental delta, so it is exactly as correct after
    a one-provider pull as after a full one.
    """
    filters = [
        Connection.workspace_id == workspace_id,
        Connection.user_id == user_id,
        Connection.paused_at.is_(None),
    ]
    if providers:
        filters.append(Connection.provider.in_(providers))
    connections = session.execute(select(Connection).where(*filters)).scalars().all()

    if not connections:
        return SyncOutcome(
            status="no_connections", connections_checked=0, connections_failed=0,
            signals_ingested=0, synced_at=datetime.now(timezone.utc),
        )

    signals_ingested = 0
    failed = 0
    errors: list[str] = []

    # Each connection's own provider fetch is independent - one dead token or
    # rate limit must never stop the rest from syncing, the same guarantee the
    # scheduled path gives every connection its own Celery task for.
    for connection in connections:
        try:
            signals_ingested += ingestion.ingest_connection(session, connection)
        except Exception:
            failed += 1
            errors.append(f"{connection.provider.value}: couldn't sync")
            logger.exception("sync_now_ingest_failed", connection_id=str(connection.id))

    # The pipeline stages, run once for the whole workspace now that every
    # connection's fresh data is in. Same functions, same order, same
    # never-fail-the-sync wrapping as app/workers/tasks.py:ingest_connection.
    for stage_name, stage in (
        ("attention", lambda: refresh_attention(session, workspace_id)),
        ("proactive", lambda: refresh_proactive_for_workspace(session, workspace_id)),
        ("intelligence", lambda: refresh_intelligence_for_workspace(session, workspace_id)),
        ("commitments", lambda: refresh_commitments_for_workspace(session, workspace_id)),
        (
            "goals",
            lambda: reassess_goals_for_workspace(
                session, workspace_id, scope_keys=affected_scope_keys(session, workspace_id)
            ),
        ),
    ):
        try:
            stage()
        except Exception:
            logger.exception(f"sync_now_{stage_name}_failed", workspace_id=str(workspace_id))

    session.commit()

    if failed == 0:
        status = "success"
    elif failed < len(connections):
        status = "partial"
    else:
        status = "failed"

    return SyncOutcome(
        status=status, connections_checked=len(connections), connections_failed=failed,
        signals_ingested=signals_ingested, synced_at=datetime.now(timezone.utc), errors=errors,
    )
