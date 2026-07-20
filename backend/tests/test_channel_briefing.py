"""Phase 2s: Channel Briefings.

This is permission-enforcement code, so the tests are mostly about what a
channel must NOT see: items from unassigned connections, findings about
another connection's data, another member's personal reminders, and
resource-scoped items that were never allow-listed.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.agent_run import AgentRun, RunStatus, TriggeredBy
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
from app.models.connection import Connection, Provider
from app.models.finding import Finding
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.channel_briefing import build_channel_briefing, channel_pending_count

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

    user = User(email="lead@acme.test", name="Lead")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.ORG_ADMIN))

    team = Team(workspace_id=workspace.id, name="development", slug="dev")
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=user.id, role=ChannelRole.CHANNEL_ADMIN))

    gmail = Connection(workspace_id=workspace.id, provider=Provider.GMAIL, org="a@x.com", repo="gmail", encrypted_token="x")
    github = Connection(workspace_id=workspace.id, provider=Provider.GITHUB, org="acme", repo="api", encrypted_token="x")
    drive = Connection(workspace_id=workspace.id, provider=Provider.GOOGLE_DRIVE, org="a@x.com", repo="drive", encrypted_token="x")
    session.add_all([gmail, github, drive])
    session.commit()

    return {"workspace": workspace, "user": user, "team": team, "gmail": gmail, "github": github, "drive": drive}


# Visibility keys off source_provider (every real detected item carries
# one), so the fixture mirrors what the detectors actually produce.
_DEFAULT_PROVIDER = {
    AttentionType.IMPORTANT_EMAIL: "gmail",
    AttentionType.UPCOMING_MEETING: "google_calendar",
    AttentionType.STALE_PR: "github",
    AttentionType.DEADLINE: "gmail",
    AttentionType.FINDING: "agent",
    AttentionType.MANUAL: None,
}


def _item(workspace, *, type_, dedupe_key, title="Item", origin=AttentionOrigin.DETECTED, priority=0.6, provider="__default__"):
    return AttentionItem(
        workspace_id=workspace.id, type=type_, origin=origin, state=AttentionState.NEW,
        dedupe_key=dedupe_key, title=title, why="because", priority=priority,
        source_provider=_DEFAULT_PROVIDER[type_] if provider == "__default__" else provider,
    )


def _assign(session, team, connection, user):
    channel_connection = ChannelConnection(team_id=team.id, connection_id=connection.id, added_by_user_id=user.id)
    session.add(channel_connection)
    session.commit()
    return channel_connection


def test_no_connections_assigned_yields_empty_briefing(session, env):
    session.add(_item(env["workspace"], type_=AttentionType.IMPORTANT_EMAIL, dedupe_key="email:m1"))
    session.commit()

    result = build_channel_briefing(session, env["team"].id, env["workspace"].id)
    assert result["no_connections"] is True
    assert result["items"] == []
    assert result["narrative"] is None


def test_only_items_from_assigned_connections_are_visible(session, env):
    """The core gate: Gmail assigned, GitHub not - so the email shows and
    the PR does not, even though both exist in the workspace."""
    session.add(_item(env["workspace"], type_=AttentionType.IMPORTANT_EMAIL, dedupe_key="email:m1", title="Client email"))
    session.add(_item(env["workspace"], type_=AttentionType.STALE_PR, dedupe_key="pr:482", title="Stale PR"))
    session.commit()
    _assign(session, env["team"], env["gmail"], env["user"])

    titles = [i.title for i in build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"]]
    assert titles == ["Client email"]


def test_assigning_more_connections_widens_the_briefing(session, env):
    session.add(_item(env["workspace"], type_=AttentionType.IMPORTANT_EMAIL, dedupe_key="email:m1", title="Client email"))
    session.add(_item(env["workspace"], type_=AttentionType.STALE_PR, dedupe_key="pr:482", title="Stale PR"))
    session.commit()
    _assign(session, env["team"], env["gmail"], env["user"])
    _assign(session, env["team"], env["github"], env["user"])

    titles = {i.title for i in build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"]}
    assert titles == {"Client email", "Stale PR"}


def test_personal_manual_reminders_never_appear_in_a_channel(session, env):
    session.add(
        _item(env["workspace"], type_=AttentionType.MANUAL, dedupe_key="manual:abc", title="Call the dentist", origin=AttentionOrigin.MANUAL)
    )
    session.commit()
    _assign(session, env["team"], env["gmail"], env["user"])

    assert build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"] == []


def test_drive_item_hidden_until_that_document_is_allow_listed(session, env):
    """Fail-closed for documents: a Drive Connection covers many files, so
    assigning it grants nothing until an admin authorizes specific ones."""
    session.add(
        _item(
            env["workspace"], type_=AttentionType.DEADLINE, dedupe_key="deadline:doc-1",
            title="Deadline in spec", provider="google_drive",
        )
    )
    session.commit()
    channel_connection = _assign(session, env["team"], env["drive"], env["user"])

    assert build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"] == []

    session.add(ChannelConnectionResource(channel_connection_id=channel_connection.id, resource_key="doc-1", resource_label="Spec"))
    session.commit()

    items = build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"]
    assert [i.title for i in items] == ["Deadline in spec"]


def test_email_deadline_is_connection_gated_not_resource_gated(session, env):
    """The documented asymmetry: an email-sourced deadline can't be
    pre-allow-listed by an admin, so Gmail assignment alone must surface it."""
    session.add(
        _item(env["workspace"], type_=AttentionType.DEADLINE, dedupe_key="deadline:m9", title="Invoice due Friday")
    )
    session.commit()
    _assign(session, env["team"], env["gmail"], env["user"])

    titles = [i.title for i in build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"]]
    assert titles == ["Invoice due Friday"]


def test_finding_visible_only_when_its_own_connection_is_assigned(session, env):
    run = AgentRun(
        workspace_id=env["workspace"].id, connection_id=env["github"].id,
        status=RunStatus.SUCCESS, triggered_by=TriggeredBy.SCHEDULE, started_at=NOW,
    )
    session.add(run)
    session.flush()
    finding = Finding(
        workspace_id=env["workspace"].id, run_id=run.id, agent="engineering", type="risk",
        severity=0.8, confidence=0.9, summary="Risky deploy", root_cause="x", suggested_action="y", evidence={},
    )
    session.add(finding)
    session.flush()
    session.add(_item(env["workspace"], type_=AttentionType.FINDING, dedupe_key=f"finding:{finding.id}", title="Risky deploy"))
    session.commit()

    # Gmail assigned, but the finding is about the GitHub connection.
    _assign(session, env["team"], env["gmail"], env["user"])
    assert build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"] == []

    _assign(session, env["team"], env["github"], env["user"])
    titles = [i.title for i in build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"]]
    assert titles == ["Risky deploy"]


def test_resolved_items_never_appear(session, env):
    done = _item(env["workspace"], type_=AttentionType.IMPORTANT_EMAIL, dedupe_key="email:m1", title="Handled")
    done.state = AttentionState.DONE
    session.add(done)
    session.commit()
    _assign(session, env["team"], env["gmail"], env["user"])

    assert build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"] == []


def test_pending_count_matches_briefing_and_costs_no_llm_call(session, env):
    session.add(_item(env["workspace"], type_=AttentionType.IMPORTANT_EMAIL, dedupe_key="email:m1"))
    session.add(_item(env["workspace"], type_=AttentionType.IMPORTANT_EMAIL, dedupe_key="email:m2"))
    session.add(_item(env["workspace"], type_=AttentionType.STALE_PR, dedupe_key="pr:1"))
    session.commit()
    _assign(session, env["team"], env["gmail"], env["user"])

    # No Groq access in tests - if this tried to narrate, it would not
    # return a clean integer.
    assert channel_pending_count(session, env["team"].id, env["workspace"].id) == 2


def test_briefing_is_isolated_between_channels(session, env):
    other = Team(workspace_id=env["workspace"].id, name="marketing", slug="mkt")
    session.add(other)
    session.flush()
    session.add(_item(env["workspace"], type_=AttentionType.STALE_PR, dedupe_key="pr:482", title="Stale PR"))
    session.commit()

    _assign(session, env["team"], env["github"], env["user"])  # dev gets GitHub

    assert len(build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"]) == 1
    assert build_channel_briefing(session, other.id, env["workspace"].id)["items"] == []
