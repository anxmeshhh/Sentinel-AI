"""Celery tasks. Each task opens its own DB session - workers are separate
OS processes from the API, so there is no session to share.

Retries use Celery's own backoff (`autoretry_for`/`retry_backoff`) rather than
a hand-rolled sleep loop, and `task_acks_late` (set in celery_app.py) means a
worker that crashes mid-task doesn't silently lose it.
"""

import uuid

import structlog
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.agent_run import TriggeredBy
from app.models.connection import Connection, Provider
from app.services import agent_orchestration, ingestion
from app.services.attention_engine import refresh_attention
from app.services.commitments import refresh_commitments_for_workspace
from app.services.goals import affected_scope_keys, reassess_goals_for_workspace
from app.services.proactive import refresh_proactive_for_workspace
from app.services.situation_engine import refresh_intelligence_for_workspace

logger = structlog.get_logger("sentinel.workers")


@celery_app.task(name="app.workers.tasks.poll_all_connections")
def poll_all_connections() -> None:
    """Celery Beat entry point - fans out one ingestion job per connection.

    Fanning out per-connection (rather than looping in-process) means one
    slow or rate-limited repo can't delay every other tenant's poll.
    """
    session = SessionLocal()
    try:
        # Paused connections are excluded at the source, so a paused repo
        # costs nothing on the schedule rather than being fetched and
        # discarded.
        connection_ids = session.execute(
            select(Connection.id).where(Connection.paused_at.is_(None))
        ).scalars().all()
        for connection_id in connection_ids:
            ingest_connection.delay(str(connection_id))
        logger.info("poll_all_connections_dispatched", connection_count=len(connection_ids))
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.poll_slack_connections")
def poll_slack_connections() -> None:
    """Slack's own fast poll. Chat is real-time, so monitored channels are
    synced on the minutes-scale slack interval rather than the 6h all-poll -
    the difference between catching an incident forming and reporting it after
    lunch. Only channels with a resource chosen and not paused; the anchor and
    paused channels cost nothing. Idempotent with the all-poll that also covers
    Slack, so the overlap is harmless."""
    session = SessionLocal()
    try:
        connection_ids = session.execute(
            select(Connection.id).where(
                Connection.provider == Provider.SLACK,
                Connection.repo != "",
                Connection.paused_at.is_(None),
            )
        ).scalars().all()
        for connection_id in connection_ids:
            ingest_connection.delay(str(connection_id))
        logger.info("poll_slack_connections_dispatched", connection_count=len(connection_ids))
    finally:
        session.close()


@celery_app.task(
    name="app.workers.tasks.ingest_connection",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=30,
    retry_backoff_max=600,
    retry_jitter=True,
)
def ingest_connection(self, connection_id: str, triggered_by: str = TriggeredBy.SCHEDULE.value) -> None:
    session = SessionLocal()
    try:
        # Celery serializes task args as JSON, so connection_id arrives as a
        # plain str - the Uuid column type needs a real uuid.UUID for session.get().
        connection = session.get(Connection, uuid.UUID(connection_id))
        if connection is None:
            logger.warning("ingest_connection_missing", connection_id=connection_id)
            return
        ingested = ingestion.ingest_connection(session, connection)
        # Attention detection rides every sync (Phase 2p) - fresh signals in,
        # fresh attention items out, no separate schedule to keep aligned.
        # Deterministic and cheap (no LLM), so running it per-connection-sync
        # costs milliseconds. Never lets a detection bug fail the sync itself.
        try:
            refresh_attention(session, connection.workspace_id)
        except Exception:
            # Roll back before the next stage. A stage that dies mid-transaction
            # leaves the session unable to execute anything, so without this a
            # single failure here silently took proactive, intelligence,
            # commitments and goals down with it - on every scheduled sync, with
            # no 500 to notice it by. Same fix as services/sync_now.py.
            session.rollback()
            logger.exception("attention_refresh_failed", workspace_id=str(connection.workspace_id))
        # Proactive detection rides the same sync, for the same reason:
        # fresh signals are exactly when a situation might have emerged,
        # strengthened or resolved. Deterministic and cheap; the LLM is only
        # reached for a situation whose evidence actually changed, so a quiet
        # workspace costs zero tokens no matter how often this runs.
        try:
            refresh_proactive_for_workspace(session, connection.workspace_id)
        except Exception:
            session.rollback()
            logger.exception("proactive_refresh_failed", workspace_id=str(connection.workspace_id))
        # Intelligence Core (Phases 2 & 3) rides the same sync: derive entities
        # from the fresh findings and correlate them into cross-provider
        # situations. Deterministic, no LLM. Wrapped like the rest so a
        # correlation bug can never fail the provider sync.
        try:
            refresh_intelligence_for_workspace(session, connection.workspace_id)
        except Exception:
            session.rollback()
            logger.exception("intelligence_refresh_failed", workspace_id=str(connection.workspace_id))
        # Commitments age on the same cycle. Purely deterministic - dates and
        # source state, no LLM - so this is milliseconds and costs nothing.
        try:
            refresh_commitments_for_workspace(session, connection.workspace_id)
        except Exception:
            session.rollback()
            logger.exception("commitment_refresh_failed", workspace_id=str(connection.workspace_id))
        # Goals sit above the others, so they are reassessed last - by now
        # attention, situations and commitments all reflect this sync.
        # Deterministic; the model is only reached when a goal's computed
        # state actually moved.
        try:
            # Narrowed to the scopes that actually hold goals. A full scan is
            # fine at this size and will not be once GitHub/Slack/Jira are
            # feeding signals in - every event would otherwise re-evaluate
            # every goal in the workspace.
            reassess_goals_for_workspace(
                session,
                connection.workspace_id,
                scope_keys=affected_scope_keys(session, connection.workspace_id),
            )
        except Exception:
            session.rollback()
            logger.exception("goal_reassess_failed", workspace_id=str(connection.workspace_id))
        # The legacy LangGraph agent/Brief pipeline is the one part of this
        # cycle that is NOT change-gated internally, so it is gated here.
        #
        # Its specialist detectors run over a 30-day signal window, so a
        # *persistent* condition (a stale flagged email, a review bottleneck,
        # a crowded calendar) produced a candidate on every single run - and
        # each run then spent an LLM call narrating it and wrote a fresh
        # immutable AgentFinding row. On Slack's 5-minute poll that is ~288
        # re-narrations a day of facts that had not changed, plus a duplicate
        # attention item per run (`_detect_findings` keys on `finding:{id}`,
        # and every run mints new ids).
        #
        # Nothing is skipped that would otherwise be found: if no new signal
        # arrived, the agents would re-read the identical window and reach the
        # identical conclusions they already recorded. Every other engine in
        # this task already works this way - proactive gates on
        # `evidence_fingerprint`, reasoning on changed situations, goals on
        # `state_fingerprint`. This brings the oldest pipeline in line with
        # them rather than inventing a new rule for it.
        #
        # A MANUAL trigger is never gated: "Re-run now" (POST /runs) is an
        # explicit request for a fresh agent pass, and answering it with
        # silence because the provider had nothing new would be a regression
        # in a user-facing action, not a saving.
        if ingested > 0 or triggered_by == TriggeredBy.MANUAL.value:
            run_agents_for_connection.delay(str(connection.id), triggered_by)
        else:
            logger.info(
                "agent_run_skipped_no_new_signals",
                connection_id=connection_id,
                workspace_id=str(connection.workspace_id),
            )
    finally:
        session.close()


@celery_app.task(
    name="app.workers.tasks.run_agents_for_connection",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    retry_backoff=15,
    retry_backoff_max=300,
    retry_jitter=True,
)
def run_agents_for_connection(self, connection_id: str, triggered_by: str = TriggeredBy.MANUAL.value) -> None:
    session = SessionLocal()
    try:
        connection = session.get(Connection, uuid.UUID(connection_id))
        if connection is None:
            logger.warning("run_agents_connection_missing", connection_id=connection_id)
            return
        agent_orchestration.run_agents_for_connection(session, connection, TriggeredBy(triggered_by))
    finally:
        session.close()
