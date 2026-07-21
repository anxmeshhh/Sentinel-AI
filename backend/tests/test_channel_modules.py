"""The three built-out channel modules: Insights, Knowledge, Prepare Me.

All three read through the same `_channel_scope` gate as Feed/Briefing, so
the properties that matter are: they see nothing without an assigned
connection, they count/list only authorized signals, and Knowledge stays
fail-closed on Drive resources.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.channel_insights import build_channel_insights
from app.services.channel_knowledge import build_channel_knowledge
from app.services.channel_prepare import list_upcoming_meetings

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
def env(session):
    ws = Workspace(name="Acme", slug=f"a-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    user = User(email="u@acme.test", name="U")
    session.add_all([ws, user])
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.ORG_ADMIN))
    team = Team(workspace_id=ws.id, name="dev", slug="dev", group_id=None)
    # group_id NOT NULL in real schema; the module services never read it, so
    # a bare team row is enough here. Give it a real group to satisfy the FK.
    from tests.hierarchy_helpers import make_group
    team.group_id = make_group(session, ws.id).id
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=user.id, role=ChannelRole.CHANNEL_ADMIN))
    gmail = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.GMAIL, org="a@x", repo="gmail", encrypted_token="x")
    drive = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.GOOGLE_DRIVE, org="a@x", repo="drive", encrypted_token="x")
    cal = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.GOOGLE_CALENDAR, org="a@x", repo="cal", encrypted_token="x")
    session.add_all([gmail, drive, cal])
    session.commit()
    return {"ws": ws, "user": user, "team": team, "gmail": gmail, "drive": drive, "cal": cal}


def _assign(session, team, connection, user):
    cc = ChannelConnection(team_id=team.id, connection_id=connection.id, added_by_user_id=user.id)
    session.add(cc)
    session.commit()
    return cc


# --- Insights -------------------------------------------------------------


def test_insights_empty_without_a_connection(session, env):
    result = build_channel_insights(session, env["team"].id)
    assert result["no_connections"] is True
    assert result["total"] == 0


def test_insights_counts_only_authorized_signals(session, env):
    for i in range(3):
        session.add(Signal(workspace_id=env["ws"].id, connection_id=env["gmail"].id, type=SignalType.EMAIL,
                           external_id=f"m{i}", actor="alice@x", payload={"subject": "hi"}, occurred_at=NOW - timedelta(days=1)))
    # A signal from an UNASSIGNED connection must never be counted.
    session.add(Signal(workspace_id=env["ws"].id, connection_id=env["cal"].id, type=SignalType.CALENDAR_EVENT,
                       external_id="e1", actor="bob@x", payload={"title": "sync"}, occurred_at=NOW - timedelta(days=1)))
    session.commit()
    _assign(session, env["team"], env["gmail"], env["user"])

    result = build_channel_insights(session, env["team"].id)
    assert result["total"] == 3  # only the 3 gmail signals, not the calendar one
    assert result["by_type"][0]["label"] == "Emails"
    assert result["top_actors"][0]["actor"] == "alice@x"


def test_insights_respects_the_time_window(session, env):
    session.add(Signal(workspace_id=env["ws"].id, connection_id=env["gmail"].id, type=SignalType.EMAIL,
                       external_id="recent", actor="a", payload={}, occurred_at=NOW - timedelta(days=5)))
    session.add(Signal(workspace_id=env["ws"].id, connection_id=env["gmail"].id, type=SignalType.EMAIL,
                       external_id="old", actor="a", payload={}, occurred_at=NOW - timedelta(days=60)))
    session.commit()
    _assign(session, env["team"], env["gmail"], env["user"])

    assert build_channel_insights(session, env["team"].id, days=30)["total"] == 1  # the 60-day-old one is excluded


# --- Knowledge (fail-closed on Drive resources) ---------------------------


def test_knowledge_empty_until_a_document_is_allow_listed(session, env):
    session.add(Signal(workspace_id=env["ws"].id, connection_id=env["drive"].id, type=SignalType.DRIVE_FILE,
                       external_id="doc-1", actor="owner", payload={"title": "Spec", "url": "https://d/1"}, occurred_at=NOW))
    session.commit()
    cc = _assign(session, env["team"], env["drive"], env["user"])

    # Assigned but nothing allow-listed - fail closed, no knowledge.
    assert build_channel_knowledge(session, env["team"].id)["documents"] == []

    session.add(ChannelConnectionResource(channel_connection_id=cc.id, resource_key="doc-1", resource_label="Spec"))
    session.commit()

    docs = build_channel_knowledge(session, env["team"].id)["documents"]
    assert len(docs) == 1
    assert docs[0]["title"] == "Spec" and docs[0]["url"] == "https://d/1"


# --- Prepare Me -----------------------------------------------------------


def test_prepare_lists_only_upcoming_authorized_meetings(session, env):
    session.add(Signal(workspace_id=env["ws"].id, connection_id=env["cal"].id, type=SignalType.CALENDAR_EVENT,
                       external_id="future", actor="org", payload={"title": "Demo", "start": (NOW + timedelta(hours=3)).isoformat()},
                       occurred_at=NOW + timedelta(hours=3)))
    session.add(Signal(workspace_id=env["ws"].id, connection_id=env["cal"].id, type=SignalType.CALENDAR_EVENT,
                       external_id="past", actor="org", payload={"title": "Old", "start": (NOW - timedelta(days=1)).isoformat()},
                       occurred_at=NOW - timedelta(days=1)))
    session.add(Signal(workspace_id=env["ws"].id, connection_id=env["cal"].id, type=SignalType.CALENDAR_EVENT,
                       external_id="cancelled", actor="org", payload={"title": "Off", "status": "cancelled", "start": (NOW + timedelta(hours=5)).isoformat()},
                       occurred_at=NOW + timedelta(hours=5)))
    session.commit()
    _assign(session, env["team"], env["cal"], env["user"])

    meetings = list_upcoming_meetings(session, env["team"].id)["meetings"]
    assert [m["title"] for m in meetings] == ["Demo"]  # future, not past, not cancelled


def test_prepare_empty_without_a_calendar_connection(session, env):
    assert list_upcoming_meetings(session, env["team"].id)["no_connections"] is True
