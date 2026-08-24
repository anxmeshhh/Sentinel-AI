"""The last two capabilities the existing data could support.

THREAD STALL turns on one question: who spoke last. "Waiting on you" and
"waiting on them" are opposite facts, and telling someone to reply to a
thread they already answered is the false-urgent the attention engine exists
to avoid - so direction is established from the mailbox owner, and a mailbox
whose owner cannot be identified is skipped rather than guessed at.

TRENDS is the only thing in Sentinel that answers "is this getting better or
worse". The history was always there - attention items carry created_at,
signals carry occurred_at - and nothing had ever read it as a series.

Both are deterministic. No LLM, no new provider, no new field.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.attention_engine import _detect_thread_stalls
from app.services.trends import risk_direction, weekly_trends

NOW = datetime.now(timezone.utc)
OWNER = "dev@acme.test"
OTHER = "client@partner.test"


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
def env(session):
    ws = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()
    user = User(email=OWNER, name="Dev")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.EMPLOYEE))
    mail = Connection(
        workspace_id=ws.id, user_id=user.id, provider=Provider.GMAIL,
        org=OWNER, repo="gmail", encrypted_token="x", last_synced_at=NOW,
    )
    session.add(mail)
    session.flush()
    session.commit()
    return {"ws": ws, "user": user, "mail": mail, "_s": session}


def _msg(env, external_id, sender, when, thread="t-1", subject="Contract question", bulk=False):
    env["_s"].add(Signal(
        workspace_id=env["ws"].id, connection_id=env["mail"].id, type=SignalType.EMAIL,
        external_id=external_id, actor=sender, occurred_at=when,
        payload={
            "thread_id": thread, "subject": subject, "from": sender,
            "to": OWNER if sender != OWNER else OTHER, "label_ids": [], "is_bulk": bulk,
        },
    ))


# --- thread stall ---------------------------------------------------------


def test_a_conversation_the_other_side_ended_is_a_stall(session, env):
    _msg(env, "m1", OWNER, NOW - timedelta(days=10))
    _msg(env, "m2", OTHER, NOW - timedelta(days=6))
    session.commit()

    found = _detect_thread_stalls(session, env["ws"].id, NOW)
    assert len(found) == 1
    assert found[0]["type"] is AttentionType.THREAD_STALL
    assert "waiting on you" in found[0]["why"]
    assert OTHER in found[0]["why"]


def test_a_thread_we_replied_to_last_is_not_a_stall(session, env):
    """The direction test. Nothing is waiting on us here."""
    _msg(env, "m1", OTHER, NOW - timedelta(days=10))
    _msg(env, "m2", OWNER, NOW - timedelta(days=6))
    session.commit()

    assert _detect_thread_stalls(session, env["ws"].id, NOW) == []


def test_a_recent_inbound_message_is_not_yet_stalled(session, env):
    """Replying within a few days is normal - a same-day nag would make the
    feed untrustworthy."""
    _msg(env, "m1", OWNER, NOW - timedelta(days=4))
    _msg(env, "m2", OTHER, NOW - timedelta(hours=6))
    session.commit()

    assert _detect_thread_stalls(session, env["ws"].id, NOW) == []


def test_a_single_inbound_email_is_not_a_conversation(session, env):
    """One cold email is unanswered_mail's job. Requiring two messages is what
    keeps the two detectors from describing the same fact twice."""
    _msg(env, "m1", OTHER, NOW - timedelta(days=8))
    session.commit()

    assert _detect_thread_stalls(session, env["ws"].id, NOW) == []


def test_bulk_mail_never_stalls(session, env):
    """A newsletter thread is not waiting on anyone."""
    _msg(env, "m1", OTHER, NOW - timedelta(days=10), bulk=True)
    _msg(env, "m2", OTHER, NOW - timedelta(days=8), bulk=True)
    session.commit()

    assert _detect_thread_stalls(session, env["ws"].id, NOW) == []


def test_a_mailbox_with_no_identifiable_owner_is_skipped(session, env):
    """Fail closed. Without an owner address the direction is unknowable, and
    guessing it would produce exactly the wrong answer half the time."""
    env["mail"].org = "Some Mailbox"
    env["mail"].github_login = None
    session.commit()
    _msg(env, "m1", OWNER, NOW - timedelta(days=10))
    _msg(env, "m2", OTHER, NOW - timedelta(days=6))
    session.commit()

    assert _detect_thread_stalls(session, env["ws"].id, NOW) == []


def test_threads_are_keyed_per_mailbox(session, env):
    """thread_id is a provider id, unique only within a mailbox - two
    mailboxes must not collide on it."""
    second = Connection(
        workspace_id=env["ws"].id, user_id=env["user"].id, provider=Provider.MICROSOFT_OUTLOOK_MAIL,
        org="dev@other.test", repo="mail", encrypted_token="x", last_synced_at=NOW,
    )
    session.add(second)
    session.flush()
    _msg(env, "m1", OWNER, NOW - timedelta(days=10))
    _msg(env, "m2", OTHER, NOW - timedelta(days=6))
    for external_id, sender, when in (
        ("n1", "dev@other.test", NOW - timedelta(days=10)),
        ("n2", OTHER, NOW - timedelta(days=6)),
    ):
        session.add(Signal(
            workspace_id=env["ws"].id, connection_id=second.id, type=SignalType.EMAIL,
            external_id=external_id, actor=sender, occurred_at=when,
            payload={"thread_id": "t-1", "subject": "Other mailbox", "from": sender,
                     "to": "x@y.test", "label_ids": [], "is_bulk": False},
        ))
    session.commit()

    found = _detect_thread_stalls(session, env["ws"].id, NOW)
    assert len(found) == 2  # same thread_id, two mailboxes, two distinct stalls
    assert len({f["dedupe_key"] for f in found}) == 2


# --- trends ---------------------------------------------------------------


def _item(env, dedupe, created, priority=0.9, state=AttentionState.NEW):
    item = AttentionItem(
        workspace_id=env["ws"].id, connection_id=env["mail"].id, type=AttentionType.IMPORTANT_EMAIL,
        origin=AttentionOrigin.DETECTED, state=state, source_provider="gmail",
        dedupe_key=dedupe, title="x", why="y", priority=priority,
    )
    env["_s"].add(item)
    env["_s"].flush()
    # created_at is server-defaulted, so it is set explicitly here to place
    # each row in a known week.
    item.created_at = created
    return item


def test_a_worse_week_reads_as_rising_risk(session, env):
    for i in range(2):
        _item(env, f"old-{i}", NOW - timedelta(days=10))
    for i in range(5):
        _item(env, f"new-{i}", NOW - timedelta(days=2))
    session.commit()

    trends = weekly_trends(session, env["ws"].id, {env["mail"].id}, now=NOW)
    critical = next(t for t in trends if t.label == "Critical findings")

    assert critical.current == 5 and critical.previous == 2
    assert critical.delta == 3 and critical.direction == "up"
    assert critical.percent_change == 150.0
    assert risk_direction(trends) == "rising"


def test_a_calmer_week_reads_as_easing(session, env):
    for i in range(6):
        _item(env, f"old-{i}", NOW - timedelta(days=10))
    _item(env, "new-0", NOW - timedelta(days=2))
    session.commit()

    trends = weekly_trends(session, env["ws"].id, {env["mail"].id}, now=NOW)
    assert risk_direction(trends) == "easing"


def test_an_unchanged_week_is_steady(session, env):
    _item(env, "old-0", NOW - timedelta(days=10))
    _item(env, "new-0", NOW - timedelta(days=2))
    session.commit()

    trends = weekly_trends(session, env["ws"].id, {env["mail"].id}, now=NOW)
    critical = next(t for t in trends if t.label == "Critical findings")
    assert critical.delta == 0 and critical.direction == "flat"
    assert risk_direction(trends) == "steady"


def test_growth_from_zero_reports_no_percentage(session, env):
    """A jump from nothing is not a percentage, and rendering one as infinite
    growth would be noise rather than information."""
    _item(env, "new-0", NOW - timedelta(days=2))
    session.commit()

    trends = weekly_trends(session, env["ws"].id, {env["mail"].id}, now=NOW)
    critical = next(t for t in trends if t.label == "Critical findings")
    assert critical.previous == 0
    assert critical.percent_change is None


def test_manual_reminders_do_not_count_as_findings(session, env):
    """Trends measure what Sentinel found, not how much the user wrote down."""
    manual = _item(env, "manual-0", NOW - timedelta(days=2))
    manual.origin = AttentionOrigin.MANUAL
    session.commit()

    trends = weekly_trends(session, env["ws"].id, {env["mail"].id}, now=NOW)
    assert next(t for t in trends if t.label == "Findings detected").current == 0


def test_there_is_no_resolved_measure(session, env):
    """Asserted rather than assumed, so nobody adds one by counting the wrong
    column. AttentionItem carries only `created_at` - nothing records WHEN a
    row moved to DONE - so "resolved this week" would really be reporting when
    those items were raised. The measure is absent on purpose until a
    resolution timestamp exists."""
    _item(env, "old-1", NOW - timedelta(days=20), state=AttentionState.DONE)
    session.commit()

    labels = {t.label for t in weekly_trends(session, env["ws"].id, {env["mail"].id}, now=NOW)}
    assert "Resolved" not in labels
    assert labels == {"Signals analysed", "Findings detected", "Critical findings"}


def test_trends_are_scoped_to_the_callers_connections(session, env):
    """The same boundary as every other read - a trend can no more span
    members than a calendar can."""
    _item(env, "mine-0", NOW - timedelta(days=2))
    session.commit()

    assert all(t.current == 0 for t in weekly_trends(session, env["ws"].id, set(), now=NOW))
