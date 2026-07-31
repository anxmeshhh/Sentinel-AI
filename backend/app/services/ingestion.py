"""Dispatches ingestion by provider, ties each client to storage: fetch since
last sync, upsert idempotently.
"""

import time
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
# Slack's first backfill is short on purpose: chat volume is high, a channel's
# operational relevance decays fast, and a long look-back would spend the rate
# limit fetching stale conversation. Fourteen days is enough to know a channel's
# baseline and catch anything still live. Bounded further by SLACK_MAX_MESSAGES.
SLACK_BACKFILL = timedelta(days=14)
SLACK_MAX_MESSAGES = 1500


def ingest_connection(session: Session, connection: Connection) -> int:
    """Pull everything new for one connection since its last sync. Returns signal count ingested."""
    # A paused connection keeps its history but stops fetching. Checked here,
    # not just in the poll, so a directly-triggered "sync now" also respects
    # the pause rather than quietly overriding a deliberate choice.
    if connection.paused_at is not None:
        logger.info("ingest_skipped_paused", connection_id=str(connection.id))
        return 0

    # An anchor - a connected account with no resource chosen yet (repo == "")
    # - has nothing to sync. Skipped generically so the scheduled poll never
    # tries to ingest a bare account grant (a Slack workspace before any
    # channel is picked, a GitHub account before any repo), which has no
    # handler and nothing to fetch.
    if not connection.repo:
        return 0

    backfill = {Provider.GITHUB: GITHUB_BACKFILL, Provider.SLACK: SLACK_BACKFILL}.get(
        connection.provider, INITIAL_BACKFILL
    )
    since = connection.last_synced_at or (datetime.now(timezone.utc) - backfill)
    signal_repo = SignalRepository(session, connection.workspace_id)

    spec = spec_for(connection.provider)
    if not spec.ingests:
        # Live-query providers have no ingestion by design. Saying so beats
        # "no handler found", which reads like an omission someone should fix.
        raise ValueError(f"{spec.label} is queried live and is never ingested")

    # A handler may report provider-specific run detail (e.g. Slack's messages
    # scanned) into this; it is folded into last_sync_meta below. Generic, so
    # the observability story is one field, not one per provider.
    metrics: dict = {}
    started = time.monotonic()
    try:
        if connection.provider == Provider.GITHUB:
            count = _ingest_github(session, connection, since, signal_repo)
        elif connection.provider == Provider.GOOGLE_CALENDAR:
            count = _ingest_google_calendar(session, connection, since, signal_repo)
        elif connection.provider == Provider.GMAIL:
            count = _ingest_gmail(session, connection, since, signal_repo)
        elif connection.provider == Provider.SLACK:
            count = _ingest_slack(session, connection, since, signal_repo, metrics)
        else:
            # The registry says this provider ingests, but nothing here does it.
            raise ValueError(f"{spec.label} declares ingestion but has no handler")
    except Exception as exc:
        # Record the failure as a metric before re-raising, so a broken sync is
        # visible (and retried by the task) rather than silent. last_synced_at
        # is untouched, so the cursor does not advance past unfetched data.
        connection.last_sync_meta = {
            "ok": False, "error": str(exc)[:200],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "at": datetime.now(timezone.utc).isoformat(),
        }
        session.commit()
        raise

    now = datetime.now(timezone.utc)
    ConnectionRepository(session, connection.workspace_id).mark_synced(connection, now)
    # Both timestamps advance here, together, and only on success - the provider
    # ingest above raises on failure, so a failed sync reaches neither line.
    # last_synced_at deliberately doubles as the ingestion cursor (`since`,
    # above): advancing it on a *failed* attempt would move the cursor past a
    # window we never fetched, silently dropping those signals. That is why it
    # cannot advance on every attempt. The consequence for health: a
    # persistently failing connection is surfaced by growing staleness (an old
    # last_synced_at) and, for lost auth, by revoked_at - not by a
    # last_synced/last_success gap, which this coupling never produces. A
    # distinct "trying but failing" state would need its own attempt column,
    # separate from the cursor; connection_state()'s ERROR branch is otherwise
    # only reached by rows synced before last_success_at existed.
    connection.last_success_at = now
    connection.last_sync_meta = {
        "ok": True, "signals": count,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "at": now.isoformat(),
        **metrics,  # provider detail (Slack: messages_scanned, participants)
    }
    session.commit()

    logger.info(
        "ingestion_complete", connection=connection.full_name, provider=connection.provider.value,
        signals_ingested=count, **metrics,
    )
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


# Re-fetch this much before the checkpoint each sync. last_synced_at is a
# wall-clock time, but a message can land during a sync (after the API's
# snapshot, before the checkpoint advances) and would otherwise fall in the gap
# between one window's end and the next's start. A small overlap closes that
# gap; idempotent upsert makes the re-fetched messages free of cost.
SLACK_SYNC_OVERLAP = timedelta(seconds=120)


def _ingest_slack(
    session: Session, connection: Connection, since: datetime, signal_repo: SignalRepository, metrics: dict
) -> int:
    """Turn a monitored channel's new messages into operational signals - never
    a copy of the messages themselves.

    Fetches only what is new since the checkpoint (incremental), then derives at
    most three deterministic signal kinds: MENTION (someone was referenced),
    FLAGGED_MESSAGE (the operational lexicon matched), and one CHANNEL_ACTIVITY
    marker per batch (the channel was alive up to time T). Everything else about
    the messages is discarded. No LLM, no semantic judgement - that is Phase 3.
    """
    from app.integrations.slack_client import SlackClient, SlackClientError
    from app.services import slack_users
    from app.services.slack_signals import SKIP_SUBTYPES, extract_mentions, match_lexicon

    oldest = max(0.0, (since - SLACK_SYNC_OVERLAP).timestamp())
    try:
        with SlackClient(decrypt_token(connection.encrypted_token)) as client:
            messages = client.channel_history(connection.repo, oldest=oldest, max_messages=SLACK_MAX_MESSAGES)
            # Cached, best-effort: names make findings readable, but must never
            # break a sync, so a failed lookup just leaves ids in place.
            names = slack_users.directory(client, connection.github_login or connection.repo)
    except SlackClientError as exc:
        if exc.is_auth:
            # The grant is dead - record it so the connection reports revoked,
            # the same observable signal GitHub has. Then raise (not caught) so
            # the sync fails loudly rather than looking empty.
            connection.revoked_at = datetime.now(timezone.utc)
            session.commit()
        raise

    count = 0
    participants: set[str] = set()
    newest_ts: float | None = None
    newest_ts_str = ""
    for m in messages:
        ts = m.get("ts")
        if not ts:
            continue
        ts_f = float(ts)
        if newest_ts is None or ts_f > newest_ts:
            newest_ts, newest_ts_str = ts_f, ts
        actor = m.get("user") or m.get("bot_id") or ""
        if actor:
            participants.add(actor)
        if m.get("subtype") in SKIP_SUBTYPES:
            continue  # a join/leave/topic change is activity, never a signal

        text = m.get("text") or ""
        occurred = datetime.fromtimestamp(ts_f, tz=timezone.utc)
        # Store readable evidence: <@U123> tokens become @name, and the author's
        # name rides along so a finding can name the person without a lookup.
        snippet = slack_users.humanize(text, names)[:200]
        author = {"actor_name": slack_users.name_for(actor, names)}
        thread = {"thread_ts": m.get("thread_ts"), "reply_count": m.get("reply_count")}

        mentions = extract_mentions(text)
        if mentions:
            signal_repo.upsert(
                connection_id=connection.id, type=SignalType.MENTION, external_id=ts, actor=actor,
                occurred_at=occurred, payload={"mentions": mentions, "snippet": snippet, **author, **thread},
            )
            count += 1

        matched = match_lexicon(text)
        if matched:
            signal_repo.upsert(
                connection_id=connection.id, type=SignalType.FLAGGED_MESSAGE, external_id=ts, actor=actor,
                occurred_at=occurred, payload={"matched": matched, "snippet": snippet, **author, **thread},
            )
            count += 1

    # One activity marker per non-empty batch, keyed on the batch's newest ts
    # (its high-water mark): a retry of the same window dedups to the same row,
    # a genuinely newer batch makes a new one. This compact "alive up to T"
    # record is what silence detection reads - not a per-message copy.
    scanned = len(messages)
    if newest_ts is not None:
        signal_repo.upsert(
            connection_id=connection.id, type=SignalType.CHANNEL_ACTIVITY, external_id=newest_ts_str, actor="",
            occurred_at=datetime.fromtimestamp(newest_ts, tz=timezone.utc),
            payload={"message_count": scanned, "participants": len(participants),
                     "window_oldest": oldest, "window_newest": newest_ts},
        )
        count += 1

    metrics["messages_scanned"] = scanned
    metrics["participants"] = len(participants)
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
