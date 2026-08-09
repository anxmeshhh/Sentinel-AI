"""Disconnecting a provider must remove everything that depends on it.

Written after a real delete failed twice on foreign keys: `signals` was the only
child with an ORM cascade, so five other tables raised IntegrityError. In the
product that is a 500 on the Disconnect button, which is why the whole
dependency graph is pinned here rather than the one path that happened to work.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.models.agent_run import AgentRun, TriggeredBy
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionType
from app.models.base import Base
from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import (
    ChannelConnectionExclusion,
    SharedConnection,
    SharedConnectionResource,
    SharedScope,
)
from app.models.signal import Signal, SignalType
from app.models.team import Team
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.repositories.connections import ConnectionRepository

NOW = datetime.now(timezone.utc)


@pytest.fixture
def session():
    """SQLite with foreign keys ENFORCED.

    This matters more than it looks. SQLite ships with `PRAGMA foreign_keys`
    OFF, so the rest of the suite silently permits deletes that MySQL rejects -
    which is exactly why the disconnect bug reached production-shaped code
    unnoticed: every test passed while the real database refused the delete.
    Turning it on here makes this file reproduce MySQL's behaviour, so the test
    below genuinely proves the fix instead of proving SQLite is lenient.
    """
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def wired(session):
    """A connection with one of EVERY kind of dependent row hanging off it."""
    ws = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()
    user = User(email="u@x.test", name="U")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.ORG_ADMIN))
    klass = WorkspaceClass(workspace_id=ws.id, name="Eng", slug=f"eng-{uuid.uuid4().hex[:6]}")
    session.add(klass)
    session.flush()
    group = Group(class_id=klass.id, name="Plat", slug=f"plat-{uuid.uuid4().hex[:6]}")
    session.add(group)
    session.flush()
    team = Team(workspace_id=ws.id, group_id=group.id, name="Team", slug=f"t-{uuid.uuid4().hex[:8]}")
    session.add(team)
    session.flush()

    conn = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.ZOOM,
                      org="me@example.com", repo="meetings", encrypted_token="x")
    other = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.GITHUB,
                       org="acme", repo="api", encrypted_token="x")
    session.add_all([conn, other])
    session.flush()

    session.add(Signal(workspace_id=ws.id, connection_id=conn.id, type=SignalType.CALENDAR_EVENT,
                       external_id="m1", actor="me@example.com", occurred_at=NOW, payload={}))
    session.add(AttentionItem(workspace_id=ws.id, connection_id=conn.id,
                              type=AttentionType.UPCOMING_MEETING, dedupe_key="meeting:m1",
                              title="Standup", why="soon", priority=0.8, source_provider="zoom",
                              origin=AttentionOrigin.DETECTED))
    run = AgentRun(workspace_id=ws.id, connection_id=conn.id,
                   triggered_by=TriggeredBy.MANUAL, started_at=NOW)
    session.add(run)
    session.flush()

    cc = ChannelConnection(team_id=team.id, connection_id=conn.id, added_by_user_id=user.id)
    sc = SharedConnection(scope_type=SharedScope.WORKSPACE, scope_id=ws.id,
                          connection_id=conn.id, added_by_user_id=user.id)
    session.add_all([cc, sc])
    session.flush()
    session.add(ChannelConnectionResource(channel_connection_id=cc.id,
                                          resource_key="k", resource_label="K"))
    session.add(SharedConnectionResource(shared_connection_id=sc.id,
                                         resource_key="k", resource_label="K"))
    # Deliberately the SAME connection the ChannelConnection above grants: the
    # model supports both rows coexisting (deny beats allow), and disconnecting
    # has to clear both.
    session.add(ChannelConnectionExclusion(team_id=team.id, connection_id=conn.id,
                                           excluded_by_user_id=user.id))
    session.commit()

    return {"ws": ws, "conn": conn, "other": other, "run": run, "_s": session}


def _count(session, model, **filters):
    rows = session.execute(select(model)).scalars().all()
    return len([r for r in rows if all(getattr(r, k) == v for k, v in filters.items())])


def test_disconnecting_removes_every_dependent_row(session, wired):
    """The bare session.delete() this replaces raised IntegrityError here."""
    conn = wired["conn"]
    repo = ConnectionRepository(session, wired["ws"].id)

    repo.disconnect(conn)

    assert _count(session, Connection, provider=Provider.ZOOM) == 0
    assert _count(session, Signal) == 0
    assert _count(session, AttentionItem) == 0
    assert _count(session, ChannelConnection) == 0
    assert _count(session, SharedConnection) == 0
    assert _count(session, ChannelConnectionExclusion) == 0
    # Grandchildren go with their parents rather than dangling.
    assert _count(session, ChannelConnectionResource) == 0
    assert _count(session, SharedConnectionResource) == 0


def test_historical_runs_survive_but_are_detached(session, wired):
    """agent_runs.connection_id is nullable precisely so history can outlive its
    source. Deleting briefs a person already read would be a worse surprise than
    an orphaned record."""
    repo = ConnectionRepository(session, wired["ws"].id)
    repo.disconnect(wired["conn"])

    runs = session.execute(select(AgentRun)).scalars().all()
    assert len(runs) == 1
    assert runs[0].connection_id is None


def test_another_connection_is_untouched(session, wired):
    """Disconnecting one provider must not disturb the others - the failure that
    would turn a small bug into a catastrophic one."""
    repo = ConnectionRepository(session, wired["ws"].id)
    repo.disconnect(wired["conn"])

    remaining = session.execute(select(Connection)).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].provider is Provider.GITHUB


def test_disconnecting_a_connection_with_no_dependents_still_works(session, wired):
    """The trivial case must not regress while fixing the complicated one."""
    repo = ConnectionRepository(session, wired["ws"].id)
    repo.disconnect(wired["other"])
    assert _count(session, Connection, provider=Provider.GITHUB) == 0


def test_a_bare_delete_still_fails_which_is_why_disconnect_exists(session, wired):
    """Pins the reason this code is not one line.

    If someone later 'simplifies' disconnect() back to session.delete(), this
    is the test that stops them - and it only works because the fixture above
    enforces foreign keys, which SQLite does not do by default.
    """
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        session.delete(wired["conn"])
        session.commit()
