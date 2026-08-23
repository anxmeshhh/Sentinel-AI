"""A calendar event belongs to whoever connected the account it came from.

Two members of one workspace share a `signals` table. Every calendar read
went through SignalRepository, which scopes by workspace_id alone - so
`/calendar`, `/calendar/month`, `/meet/history`, the Assistant's calendar
context and the AI Command orchestrator's calendar tools all returned one
member's meeting titles, attendees and joinable Meet links to another.

Attention items were gated on `connection_id` in Phase 3. Calendar signals,
which carry considerably more, were not.

These are written from the attacker's side: given a member's private calendar
in the same workspace, can anyone else reach it - and can the availability
path, which deliberately reads across calendars, leak anything about them?
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.calendar_query import (
    calendar_summary_for_assistant,
    free_slots_for_availability,
    list_calendar,
    list_calendar_month,
)
from app.services.investigation import personal_scope
from app.services.meet_query import list_meetings

NOW = datetime.now(timezone.utc)
TOMORROW = (NOW + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)

PRIVATE = "Therapy session"
TEAM = "Sprint planning"


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
    """One workspace, two members, a Google Calendar each. Both members'
    events land in the same workspace-scoped table - the condition the leak
    lived in."""
    ws = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()

    alice = User(email="alice@acme.test", name="Alice")
    bob = User(email="bob@acme.test", name="Bob")
    session.add_all([alice, bob])
    session.flush()
    session.add_all([
        Membership(workspace_id=ws.id, user_id=alice.id, role=Role.EMPLOYEE),
        # Bob is a workspace ADMIN - being an admin must not confer sight of
        # a colleague's private calendar.
        Membership(workspace_id=ws.id, user_id=bob.id, role=Role.ORG_ADMIN),
    ])

    def _conn(user):
        c = Connection(
            workspace_id=ws.id, user_id=user.id, provider=Provider.GOOGLE_CALENDAR,
            org=user.email, repo="primary", encrypted_token="x", last_synced_at=NOW,
        )
        session.add(c)
        session.flush()
        return c

    alice_cal, bob_cal = _conn(alice), _conn(bob)

    def _event(conn, title, start, meet_slug, minutes=60):
        session.add(Signal(
            workspace_id=ws.id, connection_id=conn.id, type=SignalType.CALENDAR_EVENT,
            external_id=f"ev-{uuid.uuid4().hex[:8]}", actor=conn.org, occurred_at=start,
            payload={
                "title": title,
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=minutes)).isoformat(),
                "attendee_count": 1,
                "attendee_emails": [conn.org],
                "organizer": conn.org,
                "has_meeting_link": True,
                # Distinct per event, so a test asserting one link is absent
                # is really asserting scope rather than matching itself.
                "meet_url": f"https://meet.google.com/{meet_slug}",
                "status": "confirmed",
            },
        ))

    _event(alice_cal, PRIVATE, TOMORROW, "alice-private-xyz")
    _event(bob_cal, TEAM, TOMORROW + timedelta(hours=2), "bob-team-abc")
    session.commit()

    return {"ws": ws, "alice": alice, "bob": bob, "alice_cal": alice_cal, "bob_cal": bob_cal, "_s": session}


def _mine(env, user):
    return personal_scope(env["_s"], env["ws"].id, user.id).connection_ids


# --- the read paths -------------------------------------------------------


def test_the_calendar_list_shows_only_your_own_events(session, env):
    titles = [
        s.payload["title"]
        for s in list_calendar(
            session, env["ws"].id, calendar_range="upcoming", connection_ids=_mine(env, env["bob"])
        )
    ]
    assert titles == [TEAM]
    assert PRIVATE not in titles


def test_the_month_grid_shows_only_your_own_events(session, env):
    titles = [
        s.payload["title"]
        for s in list_calendar_month(
            session, env["ws"].id, year=TOMORROW.year, month=TOMORROW.month,
            connection_ids=_mine(env, env["bob"]),
        )
    ]
    assert PRIVATE not in titles


def test_meeting_history_does_not_expose_another_members_meet_link(session, env):
    """A meeting row carries a joinable Meet URL - the most concrete thing in
    this table."""
    rows = list_meetings(
        session, env["ws"].id, meeting_range="upcoming", connection_ids=_mine(env, env["bob"])
    )
    assert [s.payload["title"] for s in rows] == [TEAM]
    assert all("alice-private-xyz" not in (s.payload.get("meet_url") or "") for s in rows)


def test_the_assistants_context_is_scoped_too(session, env):
    """The Assistant is a read path like any other - grounding it in the
    workspace would leak through the answer instead of through a list."""
    summary = calendar_summary_for_assistant(
        session, env["ws"].id, connection_ids=_mine(env, env["bob"])
    )
    assert TEAM in summary
    assert PRIVATE not in summary


def test_an_unscoped_read_would_have_leaked_it(session, env):
    """Why the filter exists, kept executable rather than as a comment.

    This is the previous behaviour - no connection_ids - and it asserts that
    it returns Alice's private event to a query made on Bob's behalf. If
    someone ever reasons the filter is redundant, this shows them the title
    it would have exposed.
    """
    titles = [
        s.payload["title"]
        for s in list_calendar(session, env["ws"].id, calendar_range="upcoming")
    ]
    assert PRIVATE in titles and TEAM in titles


def test_no_authorized_connections_returns_nothing_not_everything(session, env):
    """Fail-closed. An empty set is 'you may see none of it', which must not
    collapse into the unfiltered query."""
    assert list_calendar(session, env["ws"].id, calendar_range="upcoming", connection_ids=set()) == []
    assert list_meetings(session, env["ws"].id, meeting_range="upcoming", connection_ids=set()) == []


# --- combine, never expose ------------------------------------------------


def test_availability_across_calendars_reports_times_and_nothing_else(session, env):
    """The product rule: "3 PM is unavailable", never "Alice has therapy".

    Availability deliberately reads BOTH calendars - that is what makes it
    useful - so the guarantee cannot come from what it reads. It comes from
    what it returns: times only, no title, attendee, organiser or owner.
    """
    both = _mine(env, env["alice"]) | _mine(env, env["bob"])
    slots = free_slots_for_availability(
        session, env["ws"].id, date=TOMORROW.date().isoformat(), connection_ids=both,
        start_hour=9, end_hour=23,
    )

    assert slots, "expected at least one free gap around the two events"
    for slot in slots:
        # The whole guarantee, asserted structurally.
        assert set(slot) == {"start", "end", "minutes"}
    blob = str(slots)
    assert PRIVATE not in blob and TEAM not in blob
    assert "alice@acme.test" not in blob and "alice-private-xyz" not in blob


def test_availability_still_accounts_for_the_private_event(session, env):
    """Combining has to be real, or the privacy guarantee is just a smaller
    feature. Alice's 15:00-16:00 event must remove that hour from the shared
    availability view even though nothing about it is disclosed."""
    both = _mine(env, env["alice"]) | _mine(env, env["bob"])
    slots = free_slots_for_availability(
        session, env["ws"].id, date=TOMORROW.date().isoformat(), connection_ids=both,
        start_hour=9, end_hour=23, duration_minutes=30,
    )

    busy_start = TOMORROW  # 15:00, Alice's private event
    overlapping = [
        s for s in slots
        if datetime.fromisoformat(s["start"]) < busy_start + timedelta(hours=1)
        and datetime.fromisoformat(s["end"]) > busy_start
    ]
    assert overlapping == [], "the private event's hour was offered as free"
