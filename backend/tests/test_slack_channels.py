"""Slack channel management, over the shared provider_account helper.

Phase 1: a monitored Slack channel is a Connection, managed exactly like a
GitHub repository - add / remove / pause / classify - through provider_account,
not Slack-specific logic. These lock in that behaviour and the one thing that
differs from GitHub: a channel's id is its key and its #name is its display.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.security import encrypt_token
from app.models.base import Base
from app.models.connection import Connection, Provider, ResourcePriority
from app.services import provider_account
from app.services.slack_connections import (
    add_channel,
    connect_slack_workspace,
    monitored_channels,
    slack_workspace,
)
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind


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
    user = User(email="dev@acme.test", name="Dev")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.ORG_ADMIN))
    session.commit()
    return {"workspace": ws, "user": user}


def _connect(session, env, *, team_id="T1", team_name="Acme HQ"):
    return connect_slack_workspace(
        session, workspace_id=env["workspace"].id, user_id=env["user"].id,
        team_id=team_id, team_name=team_name, encrypted_token=encrypt_token("xoxb-1"),
    )


def _add(session, env, channel_id, name):
    return add_channel(
        session, workspace_id=env["workspace"].id, user_id=env["user"].id,
        channel_id=channel_id, channel_name=name,
    )


# --- the account anchor -----------------------------------------------------


def test_connect_creates_an_anchor(session, env):
    _connect(session, env)
    anchor = slack_workspace(session, env["workspace"].id, env["user"].id)
    assert anchor is not None
    assert anchor.repo == ""  # no channel chosen yet
    assert anchor.org == "Acme HQ"  # team name is the display
    assert anchor.github_login == "T1"  # team id is the identity
    assert monitored_channels(session, env["workspace"].id, env["user"].id) == []


def test_reconnect_same_workspace_refreshes_without_duplicating(session, env):
    _connect(session, env)
    _add(session, env, "C1", "general")
    connect_slack_workspace(
        session, workspace_id=env["workspace"].id, user_id=env["user"].id,
        team_id="T1", team_name="Acme HQ", encrypted_token=encrypt_token("xoxb-2"),
    )
    channels = monitored_channels(session, env["workspace"].id, env["user"].id)
    assert len(channels) == 1  # not duplicated
    assert channels[0].revoked_at is None


# --- channels as resources --------------------------------------------------


def test_add_channel_fills_the_anchor_then_adds_rows(session, env):
    _connect(session, env)
    first = _add(session, env, "C1", "general")
    assert first.repo == "C1"
    assert first.display_name == "#general"
    assert first.full_name == "#general"  # display wins over org/repo
    # First channel filled the anchor rather than leaving a stray empty row.
    assert len(provider_account.account_connections(session, env["workspace"].id, env["user"].id, Provider.SLACK)) == 1

    second = _add(session, env, "C2", "incidents")
    assert {c.repo for c in monitored_channels(session, env["workspace"].id, env["user"].id)} == {"C1", "C2"}
    assert second.github_login == "T1"  # shares the account identity


def test_add_is_idempotent(session, env):
    _connect(session, env)
    a = _add(session, env, "C1", "general")
    b = _add(session, env, "C1", "general")
    assert a.id == b.id
    assert len(monitored_channels(session, env["workspace"].id, env["user"].id)) == 1


def test_channel_id_is_the_key_not_the_name(session, env):
    """The name lives in display_name; the id is what uniqueness is on, so a
    rename would not orphan the channel (same id, updated name on re-add)."""
    _connect(session, env)
    ch = _add(session, env, "C1", "general")
    assert ch.repo == "C1"
    assert ch.display_name == "#general"


# --- management -------------------------------------------------------------


def test_classify_and_pause(session, env):
    _connect(session, env)
    ch = _add(session, env, "C1", "general")
    provider_account.set_priority(session, ch, ResourcePriority.CRITICAL)
    assert ch.priority is ResourcePriority.CRITICAL
    provider_account.set_paused(session, ch, paused=True)
    assert ch.paused_at is not None
    provider_account.set_paused(session, ch, paused=False)
    assert ch.paused_at is None


def test_remove_last_channel_leaves_the_account_connected(session, env):
    _connect(session, env)
    ch = _add(session, env, "C1", "general")
    provider_account.remove_resource(session, ch)
    assert monitored_channels(session, env["workspace"].id, env["user"].id) == []
    # An anchor remains, so the workspace stays connected without re-auth.
    assert slack_workspace(session, env["workspace"].id, env["user"].id) is not None


def test_switching_workspace_wipes_the_old_channels(session, env):
    _connect(session, env, team_id="T1", team_name="Acme HQ")
    _add(session, env, "C1", "general")
    # A different Slack workspace authorizes - its channels are not this one's.
    connect_slack_workspace(
        session, workspace_id=env["workspace"].id, user_id=env["user"].id,
        team_id="T2", team_name="Other Co", encrypted_token=encrypt_token("xoxb-other"),
    )
    channels = monitored_channels(session, env["workspace"].id, env["user"].id)
    assert channels == []  # old channels wiped
    assert slack_workspace(session, env["workspace"].id, env["user"].id).github_login == "T2"


# --- the shared helper really is shared -------------------------------------


def test_slack_and_github_share_the_helper_without_colliding(session, env):
    """Both providers use provider_account; a user's Slack and GitHub resources
    are independent because every query is scoped by provider."""
    _connect(session, env)
    _add(session, env, "C1", "general")
    provider_account.connect_account(
        session, workspace_id=env["workspace"].id, user_id=env["user"].id, provider=Provider.GITHUB,
        account_identity="octocat", encrypted_token=encrypt_token("gh"), anchor_org="octocat",
    )
    provider_account.add_resource(
        session, workspace_id=env["workspace"].id, user_id=env["user"].id, provider=Provider.GITHUB,
        org="octocat", repo="api",
    )
    slack = monitored_channels(session, env["workspace"].id, env["user"].id)
    github = provider_account.monitored_resources(session, env["workspace"].id, env["user"].id, Provider.GITHUB)
    assert [c.repo for c in slack] == ["C1"]
    assert [c.repo for c in github] == ["api"]
