"""Ties the LangGraph pipeline to storage: load signals, run the graph,
persist Findings/Brief, and record run status - including partial failure.
"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

from app.agents.graph import build_graph
from app.core.logging import bind_run_context, clear_run_context
from app.models.agent_run import AgentRun, RunStatus, TriggeredBy
from app.models.brief import Brief
from app.models.connection import Connection
from app.repositories.agent_runs import AgentRunRepository
from app.repositories.briefs import BriefRepository
from app.repositories.findings import AgentFindingRepository
from app.repositories.signals import SignalRepository

logger = structlog.get_logger("sentinel.orchestration")

SIGNAL_LOOKBACK = timedelta(days=30)


def run_agents_for_connection(session: Session, connection: Connection, triggered_by: TriggeredBy) -> AgentRun:
    workspace_id = connection.workspace_id
    run_repo = AgentRunRepository(session, workspace_id)

    run = run_repo.start(connection_id=connection.id, triggered_by=triggered_by)
    session.commit()  # run_id exists and is queryable even if the rest of this run fails

    bind_run_context(run_id=str(run.id), workspace_id=str(workspace_id), connection_id=str(connection.id))
    try:
        signal_repo = SignalRepository(session, workspace_id)
        since = datetime.now(timezone.utc) - SIGNAL_LOOKBACK
        signals = signal_repo.since(connection.id, since)

        graph = build_graph()
        result = graph.invoke({"signals": signals, "connection_label": connection.full_name})

        findings = result.get("findings", [])
        finding_repo = AgentFindingRepository(session, workspace_id)
        for finding in findings:
            finding.run_id = run.id
            finding_repo.add(finding)
        session.flush()

        node_errors = result.get("node_errors", {})
        brief = Brief(
            run_id=run.id,
            narrative=result.get("narrative", ""),
            top_finding_ids=result.get("top_finding_ids", []),
            data_freshness=_freshness_notes(node_errors),
        )
        BriefRepository(session, workspace_id).add(brief)

        status = _resolve_status(node_errors=node_errors, has_output=bool(findings or result.get("narrative")))
        run_repo.finish(run, status=status, node_errors=node_errors)
        session.commit()

        logger.info("agent_run_complete", status=status.value, finding_count=len(findings), node_errors=node_errors)
        return run

    except Exception as exc:
        session.rollback()
        logger.exception("agent_run_failed")
        run_repo.finish(run, status=RunStatus.FAILED, error=str(exc))
        session.commit()
        raise
    finally:
        clear_run_context()


def _resolve_status(*, node_errors: dict, has_output: bool) -> RunStatus:
    if not node_errors:
        return RunStatus.SUCCESS
    if has_output:
        return RunStatus.PARTIAL
    return RunStatus.FAILED


def _freshness_notes(node_errors: dict) -> dict:
    return {agent: f"this agent failed this run: {error}" for agent, error in node_errors.items()}
