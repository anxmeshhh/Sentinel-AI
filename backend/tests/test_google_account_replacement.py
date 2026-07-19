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
    session.add(ws)
    session.commit()
    return ws


def _gmail_connections(session, workspace_id):
    return session.execute(
        select(Connection).where(Connection.workspace_id == workspace_id, Connection.provider == Provider.GMAIL)
    ).scalars().all()


def test_first_connect_creates_three_connections(session, workspace):
    upsert_google_connections(session, workspace_id=workspace.id, google_email="a@gmail.com", encrypted_token="tok1")
    all_connections = session.execute(select(Connection)).scalars().all()
    assert {c.provider for c in all_connections} == {Provider.GMAIL, Provider.GOOGLE_CALENDAR, Provider.GOOGLE_DRIVE}
    assert all(c.org == "a@gmail.com" for c in all_connections)


def test_same_account_reconnect_only_refreshes_token(session, workspace):
    upsert_google_connections(session, workspace_id=workspace.id, google_email="a@gmail.com", encrypted_token="tok1")
    gmail = _gmail_connections(session, workspace.id)[0]
    session.add(Signal(workspace_id=workspace.id, connection_id=gmail.id, type=SignalType.EMAIL, external_id="m1", actor="tester", payload={}, occurred_at=datetime.now(timezone.utc)))
    session.commit()

    upsert_google_connections(session, workspace_id=workspace.id, google_email="a@gmail.com", encrypted_token="tok2")

    gmail_after = _gmail_connections(session, workspace.id)
    assert len(gmail_after) == 1
    assert gmail_after[0].encrypted_token == "tok2"
    assert session.execute(select(Signal)).scalars().all() != []  # same account: signals survive


def test_different_account_replaces_and_purges(session, workspace):
    upsert_google_connections(session, workspace_id=workspace.id, google_email="a@gmail.com", encrypted_token="tok1")
    gmail = _gmail_connections(session, workspace.id)[0]
    session.add(Signal(workspace_id=workspace.id, connection_id=gmail.id, type=SignalType.EMAIL, external_id="m1", actor="tester", payload={}, occurred_at=datetime.now(timezone.utc)))
    session.add(EmailSummary(workspace_id=workspace.id, message_id="m1", subject="s", sender="x", summary="sum", key_points=[], action_items=[]))
    session.commit()

    upsert_google_connections(session, workspace_id=workspace.id, google_email="b@gmail.com", encrypted_token="tok2")

    gmail_after = _gmail_connections(session, workspace.id)
    assert len(gmail_after) == 1  # replaced, never stacked
    assert gmail_after[0].org == "b@gmail.com"
    assert gmail_after[0].last_synced_at is None  # forces a fresh sync
    assert session.execute(select(Signal)).scalars().all() == []  # old account's cache purged
    assert session.execute(select(EmailSummary)).scalars().all() == []


def test_get_by_provider_prefers_newest_if_duplicates_exist(session, workspace):
    """Defense in depth: even if duplicates somehow reappear, the pick must
    be deterministic (newest token wins), never DB-order luck."""
    old = Connection(workspace_id=workspace.id, provider=Provider.GMAIL, org="a@gmail.com", repo="gmail", encrypted_token="old")
    old.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new = Connection(workspace_id=workspace.id, provider=Provider.GMAIL, org="b@gmail.com", repo="gmail", encrypted_token="new")
    new.created_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    session.add_all([old, new])
    session.commit()

    picked = ConnectionRepository(session, workspace.id).get_by_provider(Provider.GMAIL)
    assert picked.encrypted_token == "new"
