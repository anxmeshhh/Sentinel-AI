"""Reconnecting Google must never leave a workspace with two accounts'
connections mixed together - found via a real incident: the user reconnected
with a different Google account, the callback stacked a second set of
connections beside the first, and fetches then randomly used either account's
token (emails "in Gmail but not fetchable" - they were in the OTHER
account's mailbox).
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.routes.integrations import upsert_google_connections
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.email_summary import EmailSummary
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceKind
from app.repositories.connections import ConnectionRepository


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
    owner = User(email=f"owner-{uuid.uuid4().hex[:8]}@x.test", name="Owner")
    session.add_all([ws, owner])
    session.commit()
    ws.owner = owner
    return ws


def _gmail_connections(session, workspace_id):
    return session.execute(
        select(Connection).where(Connection.workspace_id == workspace_id, Connection.provider == Provider.GMAIL)
    ).scalars().all()


def test_first_connect_creates_three_connections(session, workspace):
    upsert_google_connections(session, workspace_id=workspace.id, user_id=workspace.owner.id, google_email="a@gmail.com", encrypted_token="tok1")
    all_connections = session.execute(select(Connection)).scalars().all()
    assert {c.provider for c in all_connections} == {Provider.GMAIL, Provider.GOOGLE_CALENDAR, Provider.GOOGLE_DRIVE}
    assert all(c.org == "a@gmail.com" for c in all_connections)


def test_same_account_reconnect_only_refreshes_token(session, workspace):
    upsert_google_connections(session, workspace_id=workspace.id, user_id=workspace.owner.id, google_email="a@gmail.com", encrypted_token="tok1")
    gmail = _gmail_connections(session, workspace.id)[0]
    session.add(Signal(workspace_id=workspace.id, connection_id=gmail.id, type=SignalType.EMAIL, external_id="m1", actor="tester", payload={}, occurred_at=datetime.now(timezone.utc)))
    session.commit()

    upsert_google_connections(session, workspace_id=workspace.id, user_id=workspace.owner.id, google_email="a@gmail.com", encrypted_token="tok2")

    gmail_after = _gmail_connections(session, workspace.id)
    assert len(gmail_after) == 1
    assert gmail_after[0].encrypted_token == "tok2"
    assert session.execute(select(Signal)).scalars().all() != []  # same account: signals survive


def test_different_account_replaces_and_purges(session, workspace):
    upsert_google_connections(session, workspace_id=workspace.id, user_id=workspace.owner.id, google_email="a@gmail.com", encrypted_token="tok1")
    gmail = _gmail_connections(session, workspace.id)[0]
    session.add(Signal(workspace_id=workspace.id, connection_id=gmail.id, type=SignalType.EMAIL, external_id="m1", actor="tester", payload={}, occurred_at=datetime.now(timezone.utc)))
    session.add(EmailSummary(workspace_id=workspace.id, message_id="m1", subject="s", sender="x", summary="sum", key_points=[], action_items=[]))
    session.commit()

    upsert_google_connections(session, workspace_id=workspace.id, user_id=workspace.owner.id, google_email="b@gmail.com", encrypted_token="tok2")

    gmail_after = _gmail_connections(session, workspace.id)
    assert len(gmail_after) == 1  # replaced, never stacked
    assert gmail_after[0].org == "b@gmail.com"
    assert gmail_after[0].last_synced_at is None  # forces a fresh sync
    assert session.execute(select(Signal)).scalars().all() == []  # old account's cache purged
    assert session.execute(select(EmailSummary)).scalars().all() == []


def test_two_members_keep_separate_connections_in_one_workspace(session, workspace):
    """Phase A: before per-user connections, the second member to connect
    Google overwrote the first member's row and purged their signals. Each
    member must now own an independent connection and token."""
    other = User(email=f"other-{uuid.uuid4().hex[:8]}@x.test", name="Other")
    session.add(other)
    session.commit()

    upsert_google_connections(session, workspace_id=workspace.id, user_id=workspace.owner.id, google_email="a@gmail.com", encrypted_token="tok-a")
    upsert_google_connections(session, workspace_id=workspace.id, user_id=other.id, google_email="b@gmail.com", encrypted_token="tok-b")

    assert len(_gmail_connections(session, workspace.id)) == 2

    repo = ConnectionRepository(session, workspace.id)
    assert repo.get_for_user(workspace.owner.id, Provider.GMAIL).encrypted_token == "tok-a"
    assert repo.get_for_user(other.id, Provider.GMAIL).encrypted_token == "tok-b"


def test_a_member_without_a_connection_gets_nothing_not_someone_elses(session, workspace):
    """Fail closed: no workspace-wide fallback, or one member's mailbox
    would silently answer another member's query."""
    stranger = User(email=f"stranger-{uuid.uuid4().hex[:8]}@x.test", name="Stranger")
    session.add(stranger)
    session.commit()

    upsert_google_connections(session, workspace_id=workspace.id, user_id=workspace.owner.id, google_email="a@gmail.com", encrypted_token="tok-a")

    assert ConnectionRepository(session, workspace.id).get_for_user(stranger.id, Provider.GMAIL) is None
