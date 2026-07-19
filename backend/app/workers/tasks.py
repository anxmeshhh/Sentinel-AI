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
from app.models.connection import Connection
from app.services import agent_orchestration, ingestion
from app.services.attention_engine import refresh_attention

logger = structlog.get_logger("sentinel.workers")


@celery_app.task(name="app.workers.tasks.poll_all_connections")
def poll_all_connections() -> None:
    """Celery Beat entry point - fans out one ingestion job per connection.

    Fanning out per-connection (rather than looping in-process) means one
    slow or rate-limited repo can't delay every other tenant's poll.
    """
    session = SessionLocal()
    try:
        connection_ids = session.execute(select(Connection.id)).scalars().all()
        for connection_id in connection_ids:
            ingest_connection.delay(str(connection_id))
        logger.info("poll_all_connections_dispatched", connection_count=len(connection_ids))
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
        ingestion.ingest_connection(session, connection)
        # Attention detection rides every sync (Phase 2p) - fresh signals in,
        # fresh attention items out, no separate schedule to keep aligned.
        # Deterministic and cheap (no LLM), so running it per-connection-sync
        # costs milliseconds. Never lets a detection bug fail the sync itself.
        try:
            refresh_attention(session, connection.workspace_id)
        except Exception:
            logger.exception("attention_refresh_failed", workspace_id=str(connection.workspace_id))
        run_agents_for_connection.delay(str(connection.id), triggered_by)
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
