"""GitHub as an OAuth connection: revocation, setup state, and the boundary.

The headline is the bug this closes. While GitHub was a pasted PAT there was
no refresh to fail and no credentials to ask with, so a revoked token kept
reporting `ready` - a channel depending on it looked healthy while returning
nothing. An OAuth App can ask GitHub directly, so `expired` finally means
something for GitHub.

GitHub is stubbed throughout. What is under test is everything Sentinel does
with the answer: recording revocation, refusing a repository the token cannot
read, and keeping one member's GitHub access away from another.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - registers every table before create_all
from app.core.security import encrypt_token
from app.integrations import github_auth
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.channel_readiness import ReadinessState, _state_for

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
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(workspace)
    session.flush()
    owner = User(email="owner@acme.test", name="Owner")
    other = User(email="other@acme.test", name="Other")
    session.add_all([owner, other])
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=owner.id, role=Role.ORG_ADMIN))
    session.add(Membership(workspace_id=workspace.id, user_id=other.id, role=Role.EMPLOYEE))
    session.commit()
    return {"workspace": workspace, "owner": owner, "other": other}


def _github(session, env, *, user=None, repo="api", revoked=False, synced=True):
    connection = Connection(
        workspace_id=env["workspace"].id,
        user_id=(user or env["owner"]).id,
        provider=Provider.GITHUB,
        org="acme",
        repo=repo,
        encrypted_token=encrypt_token("gho_token"),
        last_synced_at=NOW - timedelta(minutes=5) if synced else None,
        revoked_at=NOW if revoked else None,
    )
    session.add(connection)
    session.commit()
    return connection


# --- the bug this closes ---------------------------------------------------


def test_a_revoked_token_is_recorded_not_silently_tolerated(session, env, monkeypatch):
    """The whole reason for the OAuth upgrade. GitHub says the grant is gone,
    so `revoked_at` is written - which is what makes `expired` reachable."""
    monkeypatch.setattr(github_auth, "check_token", lambda _t: False)
    connection = _github(session, env)

    with pytest.raises(github_auth.GitHubAuthError, match="revoked"):
        github_auth.get_valid_token(session, connection)

    session.refresh(connection)
    assert connection.revoked_at is not None
    assert _state_for(connection) == ReadinessState.EXPIRED


def test_a_live_token_is_returned_untouched(session, env, monkeypatch):
    monkeypatch.setattr(github_auth, "check_token", lambda _t: True)
    connection = _github(session, env)

    assert github_auth.get_valid_token(session, connection) == "gho_token"
    assert connection.revoked_at is None


def test_github_being_unreachable_does_not_revoke_anything(session, env, monkeypatch):
    """The distinction that keeps this trustworthy: "GitHub had a bad minute"
    is not "the user revoked access". Collapsing them would tell people to
    reconnect a perfectly good connection during any outage."""
    monkeypatch.setattr(github_auth, "check_token", lambda _t: None)
    connection = _github(session, env)

    assert github_auth.get_valid_token(session, connection) == "gho_token"
    session.refresh(connection)
    assert connection.revoked_at is None
    assert _state_for(connection) != ReadinessState.EXPIRED


def test_an_already_revoked_connection_is_not_re_checked(session, env, monkeypatch):
    """No point asking GitHub about a token we already know is dead."""
    calls = {"n": 0}

    def _count(_token):
        calls["n"] += 1
        return True

    monkeypatch.setattr(github_auth, "check_token", _count)
    connection = _github(session, env, revoked=True)

    with pytest.raises(github_auth.GitHubAuthError):
        github_auth.get_valid_token(session, connection)
    assert calls["n"] == 0


def test_reconnecting_clears_the_revoked_flag(session, env):
    """A fresh consent is exactly the evidence the connection is alive again -
    otherwise it would stay `expired` in the checklist forever."""
    from app.api.routes.integrations import upsert_github_connection

    connection = _github(session, env, revoked=True)
    assert _state_for(connection) == ReadinessState.EXPIRED

    upsert_github_connection(
        session, workspace_id=env["workspace"].id, user_id=env["owner"].id,
        login="acme", encrypted_token=encrypt_token("gho_fresh"),
    )

    session.refresh(connection)
    assert connection.revoked_at is None


# --- a connected account is not yet a usable connection --------------------


def test_a_connection_with_no_repository_is_not_ready(session, env):
    """One token can read many repositories and Sentinel watches one, so a
    connection exists before it points anywhere. Reporting that as `ready`
    would repeat the Drive bug - healthy-looking, and providing nothing."""
    connection = _github(session, env, repo="")

    assert _state_for(connection) == ReadinessState.NEEDS_SETUP


def test_it_is_not_reported_as_disconnected_either(session, env):
    """`not_connected` would be untrue and would send the user back through
    an OAuth round trip they already completed."""
    connection = _github(session, env, repo="")

    assert _state_for(connection) != ReadinessState.NOT_CONNECTED
    assert _state_for(connection) != ReadinessState.READY


def test_choosing_a_repository_makes_it_ready(session, env):
    connection = _github(session, env, repo="")
    connection.repo = "checkout-service"
    session.commit()

    assert _state_for(connection) == ReadinessState.READY


def test_a_repo_less_connection_syncs_nothing_rather_than_failing(session, env, monkeypatch):
    """Not an error and not something to retry - the user simply has not
    finished connecting. Syncing "" would 404 on every call."""
    from app.services import ingestion

    monkeypatch.setattr(github_auth, "check_token", lambda _t: True)
    connection = _github(session, env, repo="")

    count = ingestion._ingest_github(session, connection, NOW - timedelta(days=1), None)

    assert count == 0


# --- the boundary ----------------------------------------------------------


def test_one_members_github_is_not_listed_for_another(session, env):
    """ATTACK: the owner is an ORG_ADMIN. Rank does not grant access to
    somebody else's GitHub account."""
    from app.api.routes.integrations import _github_connection_for

    _github(session, env, user=env["other"])

    with pytest.raises(HTTPException) as exc_info:
        _github_connection_for(session, env["workspace"].id, env["owner"].id)
    assert exc_info.value.status_code == 404


def test_each_person_gets_their_own_connection(session, env):
    """The Phase A model finally holds for GitHub: a token delegates one
    individual's access, so it belongs to that individual."""
    from app.api.routes.integrations import upsert_github_connection

    first = upsert_github_connection(
        session, workspace_id=env["workspace"].id, user_id=env["owner"].id,
        login="owner-gh", encrypted_token=encrypt_token("a"),
    )
    second = upsert_github_connection(
        session, workspace_id=env["workspace"].id, user_id=env["other"].id,
        login="other-gh", encrypted_token=encrypt_token("b"),
    )

    assert first.id != second.id
    assert first.user_id != second.user_id


def test_switching_github_accounts_discards_the_old_accounts_signals(session, env):
    """Those signals describe a repository the new account may not even be
    able to see - keeping them would attribute one person's work to another's
    connection."""
    from app.api.routes.integrations import upsert_github_connection

    connection = _github(session, env)
    session.add(Signal(
        workspace_id=env["workspace"].id, connection_id=connection.id, type=SignalType.PR,
        external_id="1", actor="someone", occurred_at=NOW, payload={"title": "Old work"},
    ))
    session.commit()

    upsert_github_connection(
        session, workspace_id=env["workspace"].id, user_id=env["owner"].id,
        login="a-different-account", encrypted_token=encrypt_token("c"),
    )

    assert session.execute(select(Signal)).scalars().all() == []
    session.refresh(connection)
    assert connection.repo == ""  # and it must be pointed at a repo again


def test_the_same_account_reconnecting_keeps_its_repository(session, env):
    """Re-authorizing the same account is not a reason to make someone pick
    their repository again."""
    from app.api.routes.integrations import upsert_github_connection

    connection = _github(session, env, repo="checkout-service")

    upsert_github_connection(
        session, workspace_id=env["workspace"].id, user_id=env["owner"].id,
        login="acme", encrypted_token=encrypt_token("fresh"),
    )

    session.refresh(connection)
    assert connection.repo == "checkout-service"
