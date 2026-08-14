"""Stale-signal reconciliation: a deleted provider item must stop producing findings.

Found by live testing, not by reasoning: a Zoom meeting deleted through the
Action Registry left its CALENDAR_EVENT signal behind, so the meeting detector
kept reporting "starts in 3h" for a meeting that no longer existed. Verified
against the real account - 2 stored signals, 1 real meeting.

The tests below pin both halves of the fix, and the second half is the one that
matters most: pruning must NOT happen when the fetch was incomplete, because an
empty result from a failed call is indistinguishable from "the user deleted
everything" unless the caller is explicit about it.
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.integrations.zoom_client import ZoomClient
from app.models.attention_item import AttentionItem, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.repositories.signals import SignalRepository
from app.services.attention_engine import refresh_attention

NOW = datetime.now(timezone.utc)


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
    ws = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()
    user = User(email="u@x.test", name="U")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.ORG_ADMIN))
    conn = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.ZOOM,
                      org="me@example.com", repo="meetings", encrypted_token="x", last_synced_at=NOW)
    other = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.MICROSOFT_OUTLOOK_CALENDAR,
                       org="me@example.com", repo="calendar", encrypted_token="x", last_synced_at=NOW)
    session.add_all([conn, other])
    session.flush()
    session.commit()
    return {"ws": ws, "user": user, "conn": conn, "other": other, "_s": session}


def _meeting_signal(env, external_id: str, *, hours_ahead: float = 3, conn=None):
    start = NOW + timedelta(hours=hours_ahead)
    SignalRepository(env["_s"], env["ws"].id).upsert(
        connection_id=(conn or env["conn"]).id, type=SignalType.CALENDAR_EVENT,
        external_id=external_id, actor="me@example.com", occurred_at=start,
        payload={
            "title": f"Meeting {external_id}", "start": start.isoformat(),
            "end": (start + timedelta(minutes=30)).isoformat(),
            "attendee_count": None, "meet_url": "https://zoom.us/j/1", "status": "confirmed",
            "url": "https://zoom.us/j/1",
        },
    )
    env["_s"].commit()


def _signal_ids(session, conn):
    return {
        s.external_id
        for s in session.execute(select(Signal).where(Signal.connection_id == conn.id)).scalars().all()
    }


# --- the defect itself -----------------------------------------------------


def test_a_deleted_meeting_stops_producing_a_finding(session, env):
    """The end-to-end statement of the bug. Before the fix, the finding survived
    the meeting."""
    _meeting_signal(env, "kept")
    _meeting_signal(env, "deleted-at-provider")

    refresh_attention(session, env["ws"].id)
    live = [i for i in session.execute(select(AttentionItem)).scalars().all()
            if i.type == AttentionType.UPCOMING_MEETING and i.state == AttentionState.NEW]
    assert len(live) == 2

    # The provider now returns only one of them.
    removed = SignalRepository(session, env["ws"].id).reconcile(
        connection_id=env["conn"].id, type=SignalType.CALENDAR_EVENT,
        seen_external_ids={"kept"}, window_start=NOW - timedelta(days=1),
    )
    session.commit()
    assert removed == 1
    assert _signal_ids(session, env["conn"]) == {"kept"}

    # refresh_attention already auto-completes an item whose detector stops
    # firing, so nothing in detection needed changing.
    refresh_attention(session, env["ws"].id)
    live = [i for i in session.execute(select(AttentionItem)).scalars().all()
            if i.type == AttentionType.UPCOMING_MEETING and i.state == AttentionState.NEW]
    assert len(live) == 1
    assert live[0].title == "Meeting kept"


# --- the safety argument: the window ---------------------------------------


def test_signals_outside_the_fetched_window_are_never_touched(session, env):
    """A signal missing from an INCREMENTAL fetch is not deleted - it was simply
    never asked about. Pruning it would erase real history."""
    _meeting_signal(env, "old", hours_ahead=-24 * 30)   # a month ago
    _meeting_signal(env, "current", hours_ahead=3)

    removed = SignalRepository(session, env["ws"].id).reconcile(
        connection_id=env["conn"].id, type=SignalType.CALENDAR_EVENT,
        seen_external_ids={"current"}, window_start=NOW - timedelta(days=1),
    )
    session.commit()
    assert removed == 0
    assert _signal_ids(session, env["conn"]) == {"old", "current"}


def test_a_window_end_bounds_the_prune_too(session, env):
    """Outlook enumerates [now, now+60d]. An event beyond that horizon was not
    enumerated, so its absence proves nothing."""
    _meeting_signal(env, "inside", hours_ahead=24)
    _meeting_signal(env, "beyond-horizon", hours_ahead=24 * 90)

    removed = SignalRepository(session, env["ws"].id).reconcile(
        connection_id=env["conn"].id, type=SignalType.CALENDAR_EVENT,
        seen_external_ids=set(), window_start=NOW, window_end=NOW + timedelta(days=60),
    )
    session.commit()
    assert removed == 1
    assert _signal_ids(session, env["conn"]) == {"beyond-horizon"}


def test_only_the_named_signal_type_is_pruned(session, env):
    """A complete enumeration of meetings says nothing about tasks or mail."""
    _meeting_signal(env, "m1")
    SignalRepository(session, env["ws"].id).upsert(
        connection_id=env["conn"].id, type=SignalType.TASK, external_id="t1",
        actor="", occurred_at=NOW, payload={"title": "a task"},
    )
    session.commit()

    SignalRepository(session, env["ws"].id).reconcile(
        connection_id=env["conn"].id, type=SignalType.CALENDAR_EVENT,
        seen_external_ids=set(), window_start=NOW - timedelta(days=1),
    )
    session.commit()
    remaining = session.execute(select(Signal)).scalars().all()
    assert [s.type for s in remaining] == [SignalType.TASK]


def test_another_connection_is_never_touched(session, env):
    """Signals are pruned by connection, and a connection has one owner - which
    is what keeps this scope-aware without any scope logic of its own."""
    _meeting_signal(env, "mine")
    _meeting_signal(env, "theirs", conn=env["other"])

    SignalRepository(session, env["ws"].id).reconcile(
        connection_id=env["conn"].id, type=SignalType.CALENDAR_EVENT,
        seen_external_ids=set(), window_start=NOW - timedelta(days=1),
    )
    session.commit()
    assert _signal_ids(session, env["conn"]) == set()
    assert _signal_ids(session, env["other"]) == {"theirs"}


def test_deleting_everything_is_a_legitimate_answer(session, env):
    """If the user really did cancel every meeting, the signals must go. This is
    exactly why the CALLER has to be certain its fetch succeeded."""
    _meeting_signal(env, "a")
    _meeting_signal(env, "b")

    removed = SignalRepository(session, env["ws"].id).reconcile(
        connection_id=env["conn"].id, type=SignalType.CALENDAR_EVENT,
        seen_external_ids=set(), window_start=NOW - timedelta(days=1),
    )
    session.commit()
    assert removed == 2


# --- the ambiguous-failure case, which is the dangerous one ----------------


def _zoom_client(handler) -> ZoomClient:
    client = ZoomClient("token")
    client._client = httpx.Client(
        base_url="https://api.zoom.us/v2",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer token"},
    )
    return client


def test_zoom_reports_an_incomplete_fetch_rather_than_an_empty_calendar():
    """Both meeting lists failing returns [] - identical to "no meetings". The
    stats flag is the only thing separating them, and pruning on the wrong
    reading would delete a whole calendar because of a transient API error."""
    def failing(request):
        return httpx.Response(500, json={"message": "upstream boom"})

    stats: dict = {}
    with _zoom_client(failing) as client:
        out = client.fetch_meetings(NOW - timedelta(days=1), stats=stats)

    assert out == []
    assert stats["complete"] is False


def test_zoom_reports_complete_when_both_lists_answer():
    def ok(request):
        return httpx.Response(200, json={"meetings": []})

    stats: dict = {}
    with _zoom_client(ok) as client:
        client.fetch_meetings(NOW - timedelta(days=1), stats=stats)
    assert stats["complete"] is True


def test_a_throttled_call_is_retried_rather_than_reported_incomplete(monkeypatch):
    """The live failure mode. Zoom rate-limits PER SECOND, and a sync makes
    several calls in a row - so without backoff the second list 429s, the
    enumeration reads as incomplete, and reconciliation silently never runs.
    Retrying is what keeps the prune reachable at all."""
    monkeypatch.setattr("app.integrations.zoom_client.time.sleep", lambda _: None)
    calls = {"n": 0}

    def throttled_once(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"},
                                  json={"code": 429, "message": "maximum per-second rate limit"})
        return httpx.Response(200, json={"meetings": []})

    stats: dict = {}
    with _zoom_client(throttled_once) as client:
        client.fetch_meetings(NOW - timedelta(days=1), stats=stats)

    assert calls["n"] > 1, "the 429 should have been retried"
    assert stats["complete"] is True, "a retried throttle must not look like a failed enumeration"


def test_a_persistent_429_still_reports_incomplete(monkeypatch):
    """Backoff must not paper over a genuine outage - if it never succeeds, the
    enumeration is still incomplete and pruning must stay off."""
    monkeypatch.setattr("app.integrations.zoom_client.time.sleep", lambda _: None)

    def always_throttled(request):
        return httpx.Response(429, json={"code": 429, "message": "rate limit"})

    stats: dict = {}
    with _zoom_client(always_throttled) as client:
        out = client.fetch_meetings(NOW - timedelta(days=1), stats=stats)
    assert out == []
    assert stats["complete"] is False


def test_zoom_is_incomplete_when_only_one_list_fails():
    """Partial success is still not a complete enumeration - the missing list
    could have held the meetings we would otherwise prune."""
    def half(request):
        if "previous_meetings" in str(request.url):
            return httpx.Response(500, json={"message": "boom"})
        return httpx.Response(200, json={"meetings": []})

    stats: dict = {}
    with _zoom_client(half) as client:
        client.fetch_meetings(NOW - timedelta(days=1), stats=stats)
    assert stats["complete"] is False
