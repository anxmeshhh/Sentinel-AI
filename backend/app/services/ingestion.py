"""Dispatches ingestion by provider, ties each client to storage: fetch since
last sync, upsert idempotently.
"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.orm import Session

from app.core.security import decrypt_token
from app.integrations.github_auth import get_valid_token
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
# GitHub gets a longer window: commit-and-review work moves in weeks, not
# hours, and measured against the real account every repository's most recent
# activity was already 30-40 days old - a 30-day backfill would have started
# every new GitHub connection empty. This is not a shortcut; it is matching
# the window to how the source is actually used.
GITHUB_BACKFILL = timedelta(days=90)


def ingest_connection(session: Session, connection: Connection) -> int:
    """Pull everything new for one connection since its last sync. Returns signal count ingested."""
    # A paused connection keeps its history but stops fetching. Checked here,
    # not just in the poll, so a directly-triggered "sync now" also respects
    # the pause rather than quietly overriding a deliberate choice.
    if connection.paused_at is not None:
        logger.info("ingest_skipped_paused", connection_id=str(connection.id))
        return 0

    backfill = GITHUB_BACKFILL if connection.provider == Provider.GITHUB else INITIAL_BACKFILL
    since = connection.last_synced_at or (datetime.now(timezone.utc) - backfill)
    signal_repo = SignalRepository(session, connection.workspace_id)

    spec = spec_for(connection.provider)
    if not spec.ingests:
        # Live-query providers have no ingestion by design. Saying so beats
        # "no handler found", which reads like an omission someone should fix.
        raise ValueError(f"{spec.label} is queried live and is never ingested")

    if connection.provider == Provider.GITHUB:
        count = _ingest_github(session, connection, since, signal_repo)
    elif connection.provider == Provider.GOOGLE_CALENDAR:
        count = _ingest_google_calendar(session, connection, since, signal_repo)
    elif connection.provider == Provider.GMAIL:
        count = _ingest_gmail(session, connection, since, signal_repo)
    else:
        # The registry says this provider ingests, but nothing here does it.
        raise ValueError(f"{spec.label} declares ingestion but has no handler")

    now = datetime.now(timezone.utc)
    ConnectionRepository(session, connection.workspace_id).mark_synced(connection, now)
    # last_synced_at advances on every attempt; last_success_at only when the
    # fetch actually completed without raising. The gap between them is what
    # tells a user "it's been trying but failing", which last_synced_at alone
    # would hide.
    connection.last_success_at = now
    session.commit()

    logger.info("ingestion_complete", connection=connection.full_name, provider=connection.provider.value, signals_ingested=count)
    return count


def _ingest_github(session: Session, connection: Connection, since: datetime, signal_repo: SignalRepository) -> int:
    # A connection whose repository has not been chosen yet is not a failure
    # and not something to retry - the user simply has not finished
    # connecting. Syncing "" would 404 on every call.
    if not connection.repo:
        logger.info("github_repo_not_selected", connection_id=str(connection.id))
        return 0

    # Verifies the token and records revocation on the connection, which is
    # what makes `expired` reportable for GitHub at all. Raises
    # GitHubAuthError when the user must reconnect - deliberately not caught
    # here, so the caller sees a dead connection rather than an empty sync
    # that looks like "nothing happened".
    token = get_valid_token(session, connection)
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
