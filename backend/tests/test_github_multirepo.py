"""One GitHub account, many repositories - and the independence that buys.

The value of multi-repo is not "a list": it is that each repository is a full
connection, so it can be paused, removed, shared or investigated on its own
without disturbing the others. These tests are mostly about that independence
holding, and about the account-level events (reconnect, switch) fanning out
correctly across every repo row.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.security import decrypt_token, encrypt_token
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.github_connections import (
    account_connections,
    add_repository,
    connect_github_account,
    monitored_repositories,
    remove_repository,
    set_paused,
)
from app.services.github_state import RepositoryState, github_repository_state

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
    user = User(email="dev@acme.test", name="Dev")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.ORG_ADMIN))
    session.commit()
    return {"workspace": workspace, "user": user}


def _connect(session, env, login="dev"):
    connect_github_account(
        session, workspace_id=env["workspace"].id, user_id=env["user"].id,
        login=login, encrypted_token=encrypt_token("gho_token"),
    )


def _add(session, env, org, repo):
    return add_repository(session, workspace_id=env["workspace"].id, user_id=env["user"].id, org=org, repo=repo)


# --- connecting and choosing ----------------------------------------------


def test_connecting_leaves_an_anchor_awaiting_repositories(session, env):
    _connect(session, env)

    account = account_connections(session, env["workspace"].id, env["user"].id)
    assert len(account) == 1
    assert account[0].repo == ""
    assert github_repository_state(account[0]) == RepositoryState.NEEDS_SETUP


def test_the_first_repository_fills_the_anchor_rather_than_adding_a_row(session, env):
    _connect(session, env)
    _add(session, env, "dev", "alpha")

    account = account_connections(session, env["workspace"].id, env["user"].id)
    assert len(account) == 1  # the anchor became the repo, not a second row
    assert account[0].repo == "alpha"


def test_more_repositories_add_rows(session, env):
    _connect(session, env)
    _add(session, env, "dev", "alpha")
    _add(session, env, "dev", "beta")
    _add(session, env, "acme-org", "gamma")

    watched = monitored_repositories(session, env["workspace"].id, env["user"].id)
    assert {c.full_name for c in watched} == {"dev/alpha", "dev/beta", "acme-org/gamma"}


def test_every_repository_shares_the_accounts_token(session, env):
    """One OAuth grant, reused - so a repo added later works immediately
    without re-authorizing."""
    _connect(session, env)
    a = _add(session, env, "dev", "alpha")
    b = _add(session, env, "dev", "beta")

    assert decrypt_token(a.encrypted_token) == decrypt_token(b.encrypted_token) == "gho_token"
    assert a.github_login == b.github_login == "dev"


def test_adding_the_same_repository_twice_is_idempotent(session, env):
    _connect(session, env)
    first = _add(session, env, "dev", "alpha")
    again = _add(session, env, "dev", "alpha")

    assert first.id == again.id
    assert len(monitored_repositories(session, env["workspace"].id, env["user"].id)) == 1


def test_adding_a_repo_requires_a_connected_account(session, env):
    from app.services.github_connections import GitHubAccountError

    with pytest.raises(GitHubAccountError):
        _add(session, env, "dev", "alpha")


# --- independence ----------------------------------------------------------


def test_removing_one_repository_leaves_the_others(session, env):
    _connect(session, env)
    alpha = _add(session, env, "dev", "alpha")
    _add(session, env, "dev", "beta")

    remove_repository(session, alpha)

    watched = monitored_repositories(session, env["workspace"].id, env["user"].id)
    assert {c.full_name for c in watched} == {"dev/beta"}


def test_removing_a_repository_takes_its_signals_with_it(session, env):
    _connect(session, env)
    alpha = _add(session, env, "dev", "alpha")
    session.add(Signal(
        workspace_id=env["workspace"].id, connection_id=alpha.id, type=SignalType.COMMIT,
        external_id="c1", actor="dev", occurred_at=NOW, payload={"message": "work"},
    ))
    session.commit()

    remove_repository(session, alpha)

    assert session.execute(select(Signal)).scalars().all() == []


def test_removing_the_last_repository_keeps_the_account_connected(session, env):
    """Disconnecting one repo should not force a full re-authorization to pick
    another - an anchor is left behind."""
    _connect(session, env)
    only = _add(session, env, "dev", "alpha")

    remove_repository(session, only)

    account = account_connections(session, env["workspace"].id, env["user"].id)
    assert len(account) == 1
    assert account[0].repo == ""  # anchor, still holding the token
    assert decrypt_token(account[0].encrypted_token) == "gho_token"


def test_pausing_one_repository_does_not_touch_another(session, env):
    _connect(session, env)
    alpha = _add(session, env, "dev", "alpha")
    beta = _add(session, env, "dev", "beta")

    set_paused(session, alpha, paused=True)

    assert github_repository_state(alpha) == RepositoryState.PAUSED
    assert github_repository_state(beta) != RepositoryState.PAUSED


def test_a_paused_repository_is_not_polled(session, env):
    """The whole point of pause: it stops costing anything on the schedule."""
    from app.workers import tasks

    _connect(session, env)
    alpha = _add(session, env, "dev", "alpha")
    beta = _add(session, env, "dev", "beta")
    set_paused(session, alpha, paused=True)

    live = session.execute(select(Connection.id).where(Connection.paused_at.is_(None))).scalars().all()

    assert beta.id in live
    assert alpha.id not in live


def test_a_paused_repository_syncs_nothing_even_if_triggered_directly(session, env, monkeypatch):
    """Pause has to hold at the ingestion layer too, or a "sync now" would
    quietly override a deliberate choice."""
    from app.services import ingestion

    _connect(session, env)
    alpha = _add(session, env, "dev", "alpha")
    set_paused(session, alpha, paused=True)

    # If pause were not honored, this would try to reach GitHub and fail;
    # instead it returns 0 without a client at all.
    assert ingestion.ingest_connection(session, alpha) == 0


# --- account-level events fan out -----------------------------------------


def test_reconnecting_refreshes_the_token_on_every_repository(session, env):
    _connect(session, env)
    _add(session, env, "dev", "alpha")
    _add(session, env, "dev", "beta")

    connect_github_account(
        session, workspace_id=env["workspace"].id, user_id=env["user"].id,
        login="dev", encrypted_token=encrypt_token("gho_rotated"),
    )

    for c in monitored_repositories(session, env["workspace"].id, env["user"].id):
        assert decrypt_token(c.encrypted_token) == "gho_rotated"


def test_reconnecting_clears_revocation_on_every_repository(session, env):
    _connect(session, env)
    alpha = _add(session, env, "dev", "alpha")
    beta = _add(session, env, "dev", "beta")
    alpha.revoked_at = NOW
    beta.revoked_at = NOW
    session.commit()

    connect_github_account(
        session, workspace_id=env["workspace"].id, user_id=env["user"].id,
        login="dev", encrypted_token=encrypt_token("gho_fresh"),
    )

    for c in monitored_repositories(session, env["workspace"].id, env["user"].id):
        assert c.revoked_at is None


def test_switching_accounts_wipes_every_repository_from_the_old_one(session, env):
    _connect(session, env, login="dev")
    _add(session, env, "dev", "alpha")
    _add(session, env, "dev", "beta")

    connect_github_account(
        session, workspace_id=env["workspace"].id, user_id=env["user"].id,
        login="someone-else", encrypted_token=encrypt_token("gho_other"),
    )

    account = account_connections(session, env["workspace"].id, env["user"].id)
    assert len(account) == 1  # a fresh anchor
    assert account[0].github_login == "someone-else"
    assert monitored_repositories(session, env["workspace"].id, env["user"].id) == []


# --- state derivation ------------------------------------------------------


def test_state_reports_error_when_no_sync_ever_succeeded(session, env):
    """A connection that has tried and never succeeded is failing, even though
    last_synced_at makes it look recent."""
    _connect(session, env)
    alpha = _add(session, env, "dev", "alpha")
    alpha.last_synced_at = NOW
    alpha.last_success_at = None
    session.commit()

    assert github_repository_state(alpha) == RepositoryState.ERROR


def test_state_reports_ready_after_a_successful_sync(session, env):
    _connect(session, env)
    alpha = _add(session, env, "dev", "alpha")
    alpha.last_synced_at = NOW
    alpha.last_success_at = NOW
    session.commit()

    assert github_repository_state(alpha) == RepositoryState.READY
