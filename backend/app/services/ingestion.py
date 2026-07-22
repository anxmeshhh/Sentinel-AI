"""Dispatches ingestion by provider, ties each client to storage: fetch since
last sync, upsert idempotently.
"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

from app.core.security import decrypt_token
from app.integrations.github_client import GitHubClient
from app.integrations.gmail_client import GmailClient
from app.integrations.google_auth import get_valid_access_token
from app.integrations.google_calendar_client import GoogleCalendarClient
from app.models.connection import Connection, Provider
from app.models.signal import SignalType
from app.providers import spec_for
from app.repositories.connections import ConnectionRepository
from app.repositories.signals import SignalRepository

logger = structlog.get_logger("sentinel.ingestion")

# First-ever sync for a brand new connection looks back this far.
INITIAL_BACKFILL = timedelta(days=30)


def ingest_connection(session: Session, connection: Connection) -> int:
    """Pull everything new for one connection since its last sync. Returns signal count ingested."""
    since = connection.last_synced_at or (datetime.now(timezone.utc) - INITIAL_BACKFILL)
    signal_repo = SignalRepository(session, connection.workspace_id)

    spec = spec_for(connection.provider)
    if not spec.ingests:
        # Live-query providers have no ingestion by design. Saying so beats
        # "no handler found", which reads like an omission someone should fix.
        raise ValueError(f"{spec.label} is queried live and is never ingested")

    if connection.provider == Provider.GITHUB:
        count = _ingest_github(connection, since, signal_repo)
    elif connection.provider == Provider.GOOGLE_CALENDAR:
        count = _ingest_google_calendar(session, connection, since, signal_repo)
    elif connection.provider == Provider.GMAIL:
        count = _ingest_gmail(session, connection, since, signal_repo)
    else:
        # The registry says this provider ingests, but nothing here does it.
        raise ValueError(f"{spec.label} declares ingestion but has no handler")

    ConnectionRepository(session, connection.workspace_id).mark_synced(connection, datetime.now(timezone.utc))
    session.commit()

    logger.info("ingestion_complete", connection=connection.full_name, provider=connection.provider.value, signals_ingested=count)
    return count


def _ingest_github(connection: Connection, since: datetime, signal_repo: SignalRepository) -> int:
    token = decrypt_token(connection.encrypted_token)
    count = 0

    with GitHubClient(token) as client:
        prs = client.fetch_pull_requests(connection.org, connection.repo, since)
        for pr in prs:
            pr["payload"]["changed_dirs"] = client.fetch_pr_changed_dirs(
                connection.org, connection.repo, pr["payload"]["number"]
            )
            signal_repo.upsert(
                connection_id=connection.id,
                type=SignalType.PR,
                external_id=pr["external_id"],
                actor=pr["actor"],
                payload=pr["payload"],
                occurred_at=pr["occurred_at"],
            )
            count += 1

            for review in client.fetch_reviews(connection.org, connection.repo, pr["payload"]["number"]):
                signal_repo.upsert(
                    connection_id=connection.id,
                    type=SignalType.REVIEW_SUBMITTED,
                    external_id=f"{pr['external_id']}:{review['external_id']}",
                    actor=review["actor"],
                    payload=review["payload"],
                    occurred_at=review["occurred_at"],
                )
                count += 1

        for commit in client.fetch_commits(connection.org, connection.repo, since):
            signal_repo.upsert(
                connection_id=connection.id,
                type=SignalType.COMMIT,
                external_id=commit["external_id"],
                actor=commit["actor"],
                payload=commit["payload"],
                occurred_at=commit["occurred_at"],
            )
            count += 1

        for issue in client.fetch_issues(connection.org, connection.repo, since):
            signal_repo.upsert(
                connection_id=connection.id,
                type=SignalType.ISSUE,
                external_id=issue["external_id"],
                actor=issue["actor"],
                payload=issue["payload"],
                occurred_at=issue["occurred_at"],
            )
            count += 1

    return count


def _ingest_google_calendar(session: Session, connection: Connection, since: datetime, signal_repo: SignalRepository) -> int:
    access_token = get_valid_access_token(session, connection)
    count = 0
    with GoogleCalendarClient(access_token) as client:
        for event in client.fetch_events(since):
            signal_repo.upsert(
                connection_id=connection.id,
                type=SignalType.CALENDAR_EVENT,
                external_id=event["external_id"],
                actor=event["actor"],
                payload=event["payload"],
                occurred_at=event["occurred_at"],
            )
            count += 1
    return count


def _ingest_gmail(session: Session, connection: Connection, since: datetime, signal_repo: SignalRepository) -> int:
    access_token = get_valid_access_token(session, connection)
    count = 0
    with GmailClient(access_token) as client:
        for message in client.fetch_messages(since):
            signal_repo.upsert(
                connection_id=connection.id,
                type=SignalType.EMAIL,
                external_id=message["external_id"],
                actor=message["actor"],
                payload=message["payload"],
                occurred_at=message["occurred_at"],
            )
            count += 1
    return count
