"""Slack ingestion: notable signals only, idempotent, incremental, pausable.

The Phase 2 contract, tested without a real Slack: a monitored channel's
messages become at most three deterministic signal kinds (activity, mention,
flagged) - never a copy of the messages - and the pipeline is safely resumable
(re-running produces no duplicates) and respects pause. No LLM anywhere.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.security import encrypt_token
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services import ingestion
from app.services.slack_signals import extract_mentions, match_lexicon

NOW = datetime.now(timezone.utc)


# --- the deterministic extractors (pure) ------------------------------------


def test_extract_mentions():
    assert extract_mentions("hey <@U123> and <@W99>") == {"users": ["U123", "W99"], "groups": []}
    assert extract_mentions("<!here> ship it")["groups"] == ["here"]
    assert extract_mentions("ping <!subteam^S1|@sre>")["groups"] == ["subteam:S1"]
    assert extract_mentions("no mentions here") is None
    assert extract_mentions("") is None


def test_match_lexicon():
    assert match_lexicon("we are BLOCKED and it is urgent") == ["blocked", "urgent"]
    assert match_lexicon("helpful helper") == []  # word boundaries: not "help"
    assert match_lexicon("nothing operational") == []
    assert match_lexicon(None) == []


# --- ingestion --------------------------------------------------------------


class FakeSlack:
    """Stands in for SlackClient: returns preset messages, honouring `oldest`
    so incremental behaviour can be exercised."""

    messages: list[dict] = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def channel_history(self, channel_id, *, oldest=None, max_messages=1000, page_size=200):
        return [m for m in FakeSlack.messages if oldest is None or float(m["ts"]) > oldest]


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def channel(session):
    ws = Workspace(name="Acme", slug=f"a-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()
    user = User(email="d@acme.test", name="D")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.ORG_ADMIN))
    ch = Connection(
        workspace_id=ws.id, user_id=user.id, provider=Provider.SLACK,
        org="Acme", repo="C1", display_name="#general", github_login="T1",
        encrypted_token=encrypt_token("xoxb-test"),
    )
    session.add(ch)
    session.commit()
    return ch


@pytest.fixture(autouse=True)
def fake_slack(monkeypatch):
    monkeypatch.setattr("app.integrations.slack_client.SlackClient", FakeSlack)
    FakeSlack.messages = []


def _ts(days_ago: float) -> str:
    # Live wall-clock, not a fixed module time: the incremental checkpoint is a
    # real datetime.now() at sync time, so a message's ts must be relative to
    # the same clock or a long suite run drifts them apart.
    return f"{(datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp():.6f}"


def _counts(session, conn):
    return {
        t.value: n for t, n in session.execute(
            select(Signal.type, func.count()).where(Signal.connection_id == conn.id).group_by(Signal.type)
        )
    }


def test_only_notable_signals_are_stored(session, channel):
    """Five messages, but Sentinel stores signals - not the messages. Two plain
    messages leave no per-message row; the mention and the flagged one each
    become a signal; and one activity marker sums up the batch."""
    FakeSlack.messages = [
        {"ts": _ts(1), "user": "U1", "text": "morning all"},
        {"ts": _ts(2), "user": "U2", "text": "deploy is <@U3> blocked, urgent"},  # mention + flagged
        {"ts": _ts(3), "user": "U3", "text": "hey <@U1> quick q"},  # mention only
        {"ts": _ts(4), "user": "U4", "text": "lunch?"},
        {"ts": _ts(5), "user": "U5", "text": "channel_join", "subtype": "channel_join"},  # system: skipped
    ]
    ingestion.ingest_connection(session, channel)
    c = _counts(session, channel)
    assert c.get("mention") == 2
    assert c.get("flagged_message") == 1
    assert c.get("channel_activity") == 1  # one marker for the batch
    # No signal type is a per-message copy: total < messages that carried text.
    assert sum(c.values()) == 4


def test_a_message_can_be_both_a_mention_and_flagged(session, channel):
    FakeSlack.messages = [{"ts": _ts(1), "user": "U1", "text": "<@U2> we are blocked"}]
    ingestion.ingest_connection(session, channel)
    c = _counts(session, channel)
    assert c.get("mention") == 1 and c.get("flagged_message") == 1  # same ts, different type - no collision


def test_idempotent_no_duplicates_on_rerun(session, channel):
    """Re-running the same sync produces no duplicate signals - the reliability
    guarantee. The checkpoint is reset so the exact same window is re-processed."""
    FakeSlack.messages = [
        {"ts": _ts(1), "user": "U1", "text": "<@U2> blocked"},
        {"ts": _ts(2), "user": "U2", "text": "ok"},
    ]
    ingestion.ingest_connection(session, channel)
    before = session.execute(select(func.count()).where(Signal.connection_id == channel.id)).scalar()
    channel.last_synced_at = None  # force a full re-scan of the identical window
    session.commit()
    ingestion.ingest_connection(session, channel)
    after = session.execute(select(func.count()).where(Signal.connection_id == channel.id)).scalar()
    assert before == after  # upsert dedup: identical events, same rows


def test_incremental_only_new_messages(session, channel):
    FakeSlack.messages = [{"ts": _ts(5), "user": "U1", "text": "<@U2> first"}]
    ingestion.ingest_connection(session, channel)
    first = _counts(session, channel)
    # A newer message arrives; the next sync fetches only past the checkpoint.
    FakeSlack.messages.append({"ts": _ts(0.001), "user": "U3", "text": "<@U4> later"})
    ingestion.ingest_connection(session, channel)
    after = _counts(session, channel)
    assert after["mention"] == 2  # the new one added
    assert after["channel_activity"] == 2  # a second batch marker


def test_pause_stops_ingestion(session, channel):
    FakeSlack.messages = [{"ts": _ts(1), "user": "U1", "text": "<@U2> blocked"}]
    channel.paused_at = NOW
    session.commit()
    n = ingestion.ingest_connection(session, channel)
    assert n == 0
    assert session.execute(select(func.count()).where(Signal.connection_id == channel.id)).scalar() == 0


def test_sync_metrics_are_recorded(session, channel):
    FakeSlack.messages = [
        {"ts": _ts(1), "user": "U1", "text": "<@U2> urgent"},
        {"ts": _ts(2), "user": "U2", "text": "ok"},
    ]
    ingestion.ingest_connection(session, channel)
    meta = channel.last_sync_meta
    assert meta["ok"] is True
    assert meta["messages_scanned"] == 2
    assert meta["signals"] >= 1
    assert "duration_ms" in meta and "at" in meta


def test_activity_marker_records_the_batch_not_each_message(session, channel):
    FakeSlack.messages = [
        {"ts": _ts(1), "user": "U1", "text": "a"},
        {"ts": _ts(2), "user": "U2", "text": "b"},
        {"ts": _ts(3), "user": "U1", "text": "c"},
    ]
    ingestion.ingest_connection(session, channel)
    activity = session.execute(
        select(Signal).where(Signal.connection_id == channel.id, Signal.type == SignalType.CHANNEL_ACTIVITY)
    ).scalars().all()
    assert len(activity) == 1
    assert activity[0].payload["message_count"] == 3
    assert activity[0].payload["participants"] == 2
