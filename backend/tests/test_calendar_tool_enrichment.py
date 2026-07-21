"""list_calendar_events must surface who's attending and how to join.

The signal payload has stored attendee_emails, organizer and meet_url since
the calendar client was written, but the orchestrator tool dropped them -
so the AI could report "3 attendees" but never who, and could never hand
back a joinable Meet link. This pins the enriched shape so it can't silently
regress to a count-and-calendar-link-only result again.
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
from app.models.workspace import Workspace, WorkspaceKind
from app.services.orchestrator import _execute_read_tool

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


def test_calendar_tool_surfaces_attendees_organizer_and_meet_link(session):
    ws = Workspace(name="P", slug=f"p-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.PERSONAL)
    user = User(email="u@x.test", name="U")
    session.add_all([ws, user])
    session.flush()
    conn = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.GOOGLE_CALENDAR,
                      org="u@x", repo="cal", encrypted_token="x")
    session.add(conn)
    session.flush()
    start = NOW + timedelta(days=1)
    session.add(Signal(
        workspace_id=ws.id, connection_id=conn.id, type=SignalType.CALENDAR_EVENT,
        external_id="e1", actor="priya@acme.com",
        payload={
            "title": "Q3 Review", "start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat(),
            "attendee_count": 2, "attendee_emails": ["priya@acme.com", "sam@acme.com"],
            "organizer": "priya@acme.com", "meet_url": "https://meet.google.com/abc-defg-hij",
            "url": "https://calendar.google.com/e/1",
        },
        occurred_at=start,
    ))
    session.commit()

    result = _execute_read_tool(session, ws.id, "list_calendar_events", {"range": "upcoming"}, user_id=user.id)
    assert len(result) == 1
    evt = result[0]
    # The whole point: not just a count.
    assert evt["attendee_emails"] == ["priya@acme.com", "sam@acme.com"]
    assert evt["organizer"] == "priya@acme.com"
    assert evt["meet_url"] == "https://meet.google.com/abc-defg-hij"
    assert evt["url"] == "https://calendar.google.com/e/1"


def test_calendar_tool_reports_no_meet_link_honestly(session):
    """A bare event has no attendees and no Meet link - the tool returns an
    empty list and a null meet_url so the model states the absence rather
    than inventing a link."""
    ws = Workspace(name="P", slug=f"p-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.PERSONAL)
    user = User(email="u2@x.test", name="U")
    session.add_all([ws, user])
    session.flush()
    conn = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.GOOGLE_CALENDAR,
                      org="u@x", repo="cal", encrypted_token="x")
    session.add(conn)
    session.flush()
    start = NOW + timedelta(hours=3)
    session.add(Signal(
        workspace_id=ws.id, connection_id=conn.id, type=SignalType.CALENDAR_EVENT,
        external_id="e2", actor="u@x", payload={"title": "focus block", "start": start.isoformat(), "url": "https://c/2"},
        occurred_at=start,
    ))
    session.commit()

    evt = _execute_read_tool(session, ws.id, "list_calendar_events", {"range": "upcoming"}, user_id=user.id)[0]
    assert evt["attendee_emails"] == []
    assert evt["meet_url"] is None
