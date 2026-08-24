"""'Sync Now' - app/services/sync_now.py.

Locks in: no connections is a no-op, not an error; a paused connection is
excluded; one connection's ingestion failure never blocks the others or the
downstream pipeline; and a successful sync genuinely runs the same Intelligence
Core the scheduled path runs - not a stub that just says "success".
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.correlated_situation import Situation
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services import ingestion
from app.services.sync_now import run_full_sync

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    class _Fast:
        def complete_json(self, **kwargs):
            return {"explanation": "x", "why_it_matters": "y"}

    monkeypatch.setattr("app.services.reasoning_engine.LLMClient", _Fast)


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
    user = User(email="u@acme.test", name="U")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.ORG_ADMIN))
    session.commit()
    return {"ws": ws, "user": user, "_s": session}


def _connection(env, *, paused=False, repo="payments"):
    conn = Connection(
        workspace_id=env["ws"].id, user_id=env["user"].id, provider=Provider.GITHUB,
        org="acme", repo=repo, encrypted_token="x", last_synced_at=None,
        paused_at=NOW if paused else None,
    )
    env["_s"].add(conn)
    env["_s"].commit()
    return conn


def test_no_connections_is_a_clean_no_op(session, env):
    outcome = run_full_sync(session, env["ws"].id, env["user"].id)
    assert outcome.status == "no_connections"
    assert outcome.connections_checked == 0
    assert outcome.errors == []


def test_paused_connection_is_excluded(session, env):
    _connection(env, paused=True)
    outcome = run_full_sync(session, env["ws"].id, env["user"].id)
    assert outcome.status == "no_connections"
    assert outcome.connections_checked == 0


def test_ingestion_failure_is_isolated_and_reported(session, env, monkeypatch):
    """A connection whose provider fetch blows up must not raise out of
    run_full_sync, and must not silently look like a success."""
    _connection(env)

    def _boom(session, connection):
        raise RuntimeError("token revoked")

    monkeypatch.setattr(ingestion, "ingest_connection", _boom)

    outcome = run_full_sync(session, env["ws"].id, env["user"].id)
    assert outcome.status == "failed"
    assert outcome.connections_checked == 1
    assert outcome.connections_failed == 1
    assert outcome.signals_ingested == 0
    assert len(outcome.errors) == 1


def test_providers_filter_narrows_to_one_service(session, env, monkeypatch):
    """A provider page's own Sync Now (?service=github) must touch only its
    own connections, not a sibling Slack/Zoom connection sitting in the same
    workspace."""
    github_conn = _connection(env, repo="payments")
    slack_conn = Connection(
        workspace_id=env["ws"].id, user_id=env["user"].id, provider=Provider.SLACK,
        org="acme", repo="general", encrypted_token="x", last_synced_at=None,
    )
    env["_s"].add(slack_conn)
    env["_s"].commit()

    touched: list[uuid.UUID] = []

    def _fake(session, connection):
        touched.append(connection.id)
        return 1

    monkeypatch.setattr(ingestion, "ingest_connection", _fake)

    outcome = run_full_sync(session, env["ws"].id, env["user"].id, providers=(Provider.GITHUB,))
    assert outcome.connections_checked == 1
    assert touched == [github_conn.id]  # the Slack connection was never touched


def test_one_bad_connection_does_not_block_a_good_one(session, env, monkeypatch):
    good = _connection(env, repo="payments")
    bad = _connection(env, repo="broken")

    def _fake(session, connection):
        if connection.id == bad.id:
            raise RuntimeError("rate limited")
        return 5

    monkeypatch.setattr(ingestion, "ingest_connection", _fake)

    outcome = run_full_sync(session, env["ws"].id, env["user"].id)
    assert outcome.status == "partial"
    assert outcome.connections_checked == 2
    assert outcome.connections_failed == 1
    assert outcome.signals_ingested == 5  # the good connection's count still counted
    assert good.id != bad.id  # sanity - two distinct connections were made


def test_successful_sync_runs_the_real_pipeline(session, env, monkeypatch):
    """Not just 'status: success' - the same Intelligence Core the scheduled
    path runs must have actually produced a Situation from findings that
    exist once the (mocked) ingest has run.

    The signals are real Signal rows (not pre-built AttentionItems) because
    run_full_sync genuinely calls refresh_attention() before the Intelligence
    Core - exactly like the scheduled path - and refresh_attention
    auto-resolves any DETECTED item that isn't freshly re-derived from real
    signal data on every pass. A stale, unmerged PR signal survives that
    reconciliation because the detector re-finds it every time.
    """
    conn = _connection(env)

    def _fake_ingest(s, connection):
        # Simulate a provider fetch landing two stale PR signals on the same
        # repo - what a real ingest_connection would leave behind in the DB.
        s.add_all([
            Signal(
                workspace_id=env["ws"].id, connection_id=connection.id, type=SignalType.PR,
                external_id=f"pr-{n}", actor="dev1",
                payload={"title": f"PR {n}", "url": "https://gh", "number": n, "merged_at": None},
                occurred_at=NOW - timedelta(days=5),
            )
            for n in (1, 2)
        ])
        s.commit()
        return 2

    monkeypatch.setattr(ingestion, "ingest_connection", _fake_ingest)

    outcome = run_full_sync(session, env["ws"].id, env["user"].id)

    assert outcome.status == "success"
    assert outcome.connections_checked == 1
    assert outcome.connections_failed == 0
    assert outcome.signals_ingested == 2

    situations = session.execute(select(Situation).where(Situation.workspace_id == env["ws"].id)).scalars().all()
    assert len(situations) == 1  # the Intelligence Core actually ran, not a stub


def test_a_connection_that_dies_mid_transaction_does_not_500_the_sync(session, env, monkeypatch):
    """The real-world failure, which the plain-RuntimeError test above misses.

    A provider fetch that blows up AFTER touching the database leaves the
    transaction in a failed state, and SQLAlchemy then raises on every
    subsequent statement until someone rolls back. Without a rollback in the
    ingest loop, one dead connection did not degrade the sync - it destroyed
    it: all five downstream stages failed instantly on their first query (the
    production logs showed them failing at the same microsecond, which is what
    gave it away) and the final commit raised out of the route as a 500.

    Reproduced by violating a NOT NULL constraint, because "the session is
    poisoned" is the actual precondition - a failure that never touched the
    database, like the one above, cannot expose this.
    """
    from app.models.signal import Signal, SignalType

    _connection(env)

    def _boom_dirty(session, connection):
        session.add(Signal(
            workspace_id=env["ws"].id, connection_id=None,  # NOT NULL - poisons the transaction
            type=SignalType.PR, external_id="x", actor="a",
            occurred_at=datetime.now(timezone.utc), payload={},
        ))
        session.flush()

    monkeypatch.setattr(ingestion, "ingest_connection", _boom_dirty)

    # Must return an outcome rather than raising - the route turns an escape
    # into a 500.
    outcome = run_full_sync(session, env["ws"].id, env["user"].id)

    assert outcome.status == "failed"
    assert outcome.connections_failed == 1
    # The session survives, which is the whole point: the stages after the
    # failure could actually run.
    assert session.query(Signal).count() == 0


def test_a_failing_connection_leaves_the_session_usable(session, env, monkeypatch):
    """The isolation promise, stated as a property rather than a status code:
    after a connection dies mid-transaction, the session can still be read."""
    from app.models.signal import Signal, SignalType
    from app.models.attention_item import AttentionItem

    _connection(env)

    def _boom_dirty(session, connection):
        session.add(Signal(
            workspace_id=env["ws"].id, connection_id=None,
            type=SignalType.PR, external_id="y", actor="a",
            occurred_at=datetime.now(timezone.utc), payload={},
        ))
        session.flush()

    monkeypatch.setattr(ingestion, "ingest_connection", _boom_dirty)
    run_full_sync(session, env["ws"].id, env["user"].id)

    # Would raise PendingRollbackError if the rollback were missing.
    assert session.query(AttentionItem).count() >= 0
