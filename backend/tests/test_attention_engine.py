"""Phase 2p: the Attention Engine.

The properties that matter: precise detection (conservative rules), safe
re-runs (dedupe, no resurrection of resolved items), honest auto-resolution
(facts that stop qualifying complete themselves), and lazy snooze
resurfacing.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceKind
from app.services.attention_engine import list_attention, refresh_attention

NOW = datetime.now(timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def workspace(session):
    ws = Workspace(name="Personal", slug=f"p-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.PERSONAL)
    user = User(email=f"u-{uuid.uuid4().hex[:8]}@gmail.com", name="Owner")
    session.add_all([ws, user])
    session.flush()
    connection = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.GMAIL, org="a@gmail.com", repo="gmail", encrypted_token="x")
    session.add(connection)
    session.commit()
    ws.test_connection = connection  # convenience for tests
    return ws


def _email_signal(
    workspace, external_id: str, labels: list[str], age_days: int = 1,
    subject: str = "Test subject", sender: str = "Alice <alice@example.com>",
):
    return Signal(
        workspace_id=workspace.id, connection_id=workspace.test_connection.id,
        type=SignalType.EMAIL, external_id=external_id, actor="sender@example.com",
        payload={"subject": subject, "from": sender, "label_ids": labels},
        occurred_at=NOW - timedelta(days=age_days),
    )


def _meeting_signal(workspace, external_id: str, start: datetime, status: str = "confirmed", title: str = "Sprint Sync"):
    return Signal(
        workspace_id=workspace.id, connection_id=workspace.test_connection.id,
        type=SignalType.CALENDAR_EVENT, external_id=external_id, actor="organizer",
        payload={"title": title, "start": start.isoformat(), "status": status, "url": "https://cal", "attendee_count": 3},
        occurred_at=start,
    )


def _pr_signal(workspace, external_id: str, age_days: int, merged: bool = False):
    return Signal(
        workspace_id=workspace.id, connection_id=workspace.test_connection.id,
        type=SignalType.PR, external_id=external_id, actor="dev1",
        payload={"title": f"PR {external_id}", "url": "https://gh", "number": 1, "merged_at": NOW.isoformat() if merged else None},
        occurred_at=NOW - timedelta(days=age_days),
    )


def test_starred_unread_email_detected_with_factual_why(session, workspace):
    session.add(_email_signal(workspace, "m1", ["UNREAD", "STARRED", "INBOX"], age_days=2))
    session.commit()

    items = refresh_attention(session, workspace.id)
    assert len(items) == 1
    assert items[0].type == AttentionType.IMPORTANT_EMAIL
    assert "Starred, still unread" in items[0].why
    assert "Alice" in items[0].why
    assert items[0].origin == AttentionOrigin.DETECTED


def test_promotional_important_email_not_detected(session, workspace):
    """Gmail marks routine promos IMPORTANT - precision requires excluding
    promotional/social categories unless the user starred it themselves."""
    session.add(_email_signal(workspace, "m2", ["UNREAD", "IMPORTANT", "CATEGORY_PROMOTIONS"]))
    session.commit()
    assert refresh_attention(session, workspace.id) == []


def test_read_email_never_detected(session, workspace):
    session.add(_email_signal(workspace, "m3", ["STARRED", "INBOX"]))  # no UNREAD
    session.commit()
    assert refresh_attention(session, workspace.id) == []


def test_meeting_within_24h_detected_cancelled_not(session, workspace):
    session.add(_meeting_signal(workspace, "e1", NOW + timedelta(hours=3)))
    session.add(_meeting_signal(workspace, "e2", NOW + timedelta(hours=5), status="cancelled"))
    session.add(_meeting_signal(workspace, "e3", NOW + timedelta(hours=40)))  # beyond horizon
    session.commit()

    items = refresh_attention(session, workspace.id)
    assert len(items) == 1
    assert items[0].type == AttentionType.UPCOMING_MEETING
    assert items[0].due_at is not None


def test_stale_open_pr_detected_merged_not(session, workspace):
    session.add(_pr_signal(workspace, "pr1", age_days=6))
    session.add(_pr_signal(workspace, "pr2", age_days=10, merged=True))
    session.add(_pr_signal(workspace, "pr3", age_days=1))  # too fresh
    session.commit()

    items = refresh_attention(session, workspace.id)
    assert len(items) == 1
    assert items[0].type == AttentionType.STALE_PR
    assert "6 days" in items[0].why


def test_rerun_updates_in_place_never_duplicates(session, workspace):
    session.add(_email_signal(workspace, "m1", ["UNREAD", "STARRED"], age_days=1))
    session.commit()

    refresh_attention(session, workspace.id)
    refresh_attention(session, workspace.id)
    refresh_attention(session, workspace.id)

    all_items = session.execute(select(AttentionItem)).scalars().all()
    assert len(all_items) == 1


def test_done_item_not_resurrected_by_redetection(session, workspace):
    """The core trust property: marking something done means done, even
    though the underlying fact (still unread in Gmail) hasn't changed."""
    session.add(_email_signal(workspace, "m1", ["UNREAD", "STARRED"]))
    session.commit()

    items = refresh_attention(session, workspace.id)
    items[0].state = AttentionState.DONE
    session.commit()

    items_after = refresh_attention(session, workspace.id)
    assert items_after == []  # not re-listed
    row = session.execute(select(AttentionItem)).scalar_one()
    assert row.state == AttentionState.DONE  # and still done in the DB


def test_resolved_fact_auto_completes_item(session, workspace):
    """Email gets read in Gmail -> next sync updates labels -> the item
    should complete itself instead of nagging forever."""
    signal = _email_signal(workspace, "m1", ["UNREAD", "STARRED"])
    session.add(signal)
    session.commit()
    refresh_attention(session, workspace.id)

    signal.payload = {**signal.payload, "label_ids": ["STARRED", "INBOX"]}  # read now
    session.commit()

    assert refresh_attention(session, workspace.id) == []
    row = session.execute(select(AttentionItem)).scalar_one()
    assert row.state == AttentionState.DONE


def test_snooze_resurfaces_after_time_passes(session, workspace):
    session.add(_email_signal(workspace, "m1", ["UNREAD", "STARRED"]))
    session.commit()
    items = refresh_attention(session, workspace.id)

    items[0].state = AttentionState.SNOOZED
    items[0].snoozed_until = NOW - timedelta(minutes=1)  # already elapsed
    session.commit()

    resurfaced = list_attention(session, workspace.id)
    assert len(resurfaced) == 1
    assert resurfaced[0].state == AttentionState.NEW
    assert resurfaced[0].snoozed_until is None


def test_snoozed_future_item_stays_hidden(session, workspace):
    session.add(_email_signal(workspace, "m1", ["UNREAD", "STARRED"]))
    session.commit()
    items = refresh_attention(session, workspace.id)
    items[0].state = AttentionState.SNOOZED
    items[0].snoozed_until = NOW + timedelta(days=1)
    session.commit()

    assert list_attention(session, workspace.id) == []


def test_repeated_sender_is_filtered_out_of_attention(session, workspace):
    """Phase 2v: measured on a real inbox, repetition was the single
    strongest noise signal - job boards blasting the same thing all week."""
    for i in range(4):
        session.add(
            _email_signal(workspace, f"m{i}", ["UNREAD", "IMPORTANT", "INBOX"], subject=f"We found a job {i}", sender="Abekus <hello@abekus.co>")
        )
    session.commit()

    assert refresh_attention(session, workspace.id) == []


def test_automated_sender_is_filtered_out(session, workspace):
    session.add(
        _email_signal(workspace, "m1", ["UNREAD", "IMPORTANT", "INBOX"], subject="Dev News", sender="OpenAI <noreply@email.openai.com>")
    )
    session.commit()

    assert refresh_attention(session, workspace.id) == []


def test_starring_always_beats_the_noise_filters(session, workspace):
    """An explicit human judgment about a specific message must never be
    overridden by a heuristic about its sender."""
    session.add(
        _email_signal(workspace, "m1", ["UNREAD", "STARRED", "IMPORTANT"], subject="Newsletter", sender="News <noreply@news.example.com>")
    )
    session.commit()

    items = refresh_attention(session, workspace.id)
    assert len(items) == 1
    assert items[0].type == AttentionType.IMPORTANT_EMAIL


def test_identical_notification_is_shown_once(session, workspace):
    """"Your domain is expiring" arriving twice should occupy one slot."""
    for i in range(2):
        session.add(
            _email_signal(workspace, f"m{i}", ["UNREAD", "IMPORTANT", "INBOX"], subject="You have domain(s) expiring soon", sender="Hostinger <team@hostinger.com>")
        )
    session.commit()

    assert len(refresh_attention(session, workspace.id)) == 1


def test_bulk_mail_does_not_produce_deadlines(session, workspace):
    """Marketing is full of genuine dates that aren't the user's deadlines -
    "IPO closing today" was a real false positive before this."""
    session.add(
        _email_signal(workspace, "m1", ["UNREAD", "IMPORTANT", "INBOX"], subject="IPO closing today: SBI Funds", sender="Alerts <noreply@fund.example.com>")
    )
    session.commit()

    assert refresh_attention(session, workspace.id) == []


def test_deadline_detected_from_email_subject(session, workspace):
    session.add(_email_signal(workspace, "m1", ["INBOX"], subject="Invoice INV-2291 is due in 3 days"))
    session.commit()

    items = refresh_attention(session, workspace.id)
    assert len(items) == 1
    assert items[0].type == AttentionType.DEADLINE
    assert items[0].due_at is not None
    assert "in 3 days" in items[0].why


def test_deadline_supersedes_the_plain_email_item_for_the_same_message(session, workspace):
    """One fact, one item. A dated important email trips two detectors; the
    deadline carries more information, so it wins."""
    session.add(
        _email_signal(workspace, "m1", ["UNREAD", "STARRED", "INBOX"], subject="Contract expires in 5 days")
    )
    session.commit()

    items = refresh_attention(session, workspace.id)
    assert len(items) == 1
    assert items[0].type == AttentionType.DEADLINE


def test_ordinary_email_subject_produces_no_deadline(session, workspace):
    session.add(_email_signal(workspace, "m1", ["UNREAD", "STARRED"], subject="Notes from Friday's review"))
    session.commit()

    items = refresh_attention(session, workspace.id)
    assert [i.type for i in items] == [AttentionType.IMPORTANT_EMAIL]


def test_imminent_deadline_outranks_a_starred_email(session, workspace):
    session.add(_email_signal(workspace, "m1", ["UNREAD", "STARRED"], subject="Please review the deck"))
    session.add(_email_signal(workspace, "m2", ["INBOX"], subject="Renewal deadline tomorrow"))
    session.commit()

    items = refresh_attention(session, workspace.id)
    assert items[0].type == AttentionType.DEADLINE


def test_sorted_by_priority_then_due(session, workspace):
    session.add(_email_signal(workspace, "m1", ["UNREAD", "IMPORTANT", "INBOX"]))  # 0.6
    session.add(_meeting_signal(workspace, "e1", NOW + timedelta(hours=2)))  # 0.8
    session.commit()

    items = refresh_attention(session, workspace.id)
    assert [i.type for i in items] == [AttentionType.UPCOMING_MEETING, AttentionType.IMPORTANT_EMAIL]
