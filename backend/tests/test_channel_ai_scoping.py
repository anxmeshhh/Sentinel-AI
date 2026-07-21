"""Phase 2m: Channel AI - tests the parts of orchestrator.py that don't
require a real LLM call: tool-schema filtering by assigned Connection,
connection lookup honoring Channel assignment, resource-level rejection for
Drive files, the "no Connections assigned" short-circuit (which must never
reach the LLM), and Channel AI history logging.
"""

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.channel_ai_history import ChannelAIHistoryEntry
from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
from app.models.connection import Connection, Provider
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.orchestrator import TOOL_PROVIDERS, _execute_read_tool, _get_connection, _tool_schemas, run_command_stream

from tests.hierarchy_helpers import make_group


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


def _setup(session):
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(workspace)
    session.flush()

    user = User(email="user@acme.test", name="User")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.EMPLOYEE))

    team = Team(workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, name="development", slug="dev")
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=user.id, role=ChannelRole.CHANNEL_ADMIN))

    drive_connection = Connection(workspace_id=workspace.id, user_id=user.id, provider=Provider.GOOGLE_DRIVE, org="user@gmail.com", repo="drive", encrypted_token="x")
    gmail_connection = Connection(workspace_id=workspace.id, user_id=user.id, provider=Provider.GMAIL, org="user@gmail.com", repo="gmail", encrypted_token="x")
    session.add_all([drive_connection, gmail_connection])
    session.commit()

    return workspace, team, user, drive_connection, gmail_connection


def test_tool_schemas_unfiltered_when_no_team_scoping():
    """team_id=None (the original, still-used plain AI Command) must behave
    exactly as before this phase - every tool available."""
    schemas = _tool_schemas(None)
    names = {s["function"]["name"] for s in schemas}
    assert names == set(TOOL_PROVIDERS.keys())


def test_tool_schemas_filtered_to_assigned_providers():
    schemas = _tool_schemas({Provider.GOOGLE_DRIVE})
    names = {s["function"]["name"] for s in schemas}
    assert names == {"search_drive", "read_drive_file"}


def test_tool_schemas_empty_set_yields_no_tools():
    assert _tool_schemas(set()) == []


def test_get_connection_workspace_wide_when_team_id_none(session):
    workspace, team, user, drive_connection, _ = _setup(session)
    found = _get_connection(session, workspace.id, None, Provider.GOOGLE_DRIVE, user_id=user.id)
    assert found is not None and found.id == drive_connection.id


def test_get_connection_none_when_not_assigned_to_channel(session):
    """The core enforcement property: a Connection existing at the
    Workspace level is NOT enough once a Channel is scoping the request -
    it must actually be assigned."""
    workspace, team, user, drive_connection, _ = _setup(session)
    found = _get_connection(session, workspace.id, team.id, Provider.GOOGLE_DRIVE, user_id=user.id)
    assert found is None


def test_get_connection_found_when_assigned_to_channel(session):
    workspace, team, user, drive_connection, _ = _setup(session)
    session.add(ChannelConnection(team_id=team.id, connection_id=drive_connection.id, added_by_user_id=user.id))
    session.commit()

    found = _get_connection(session, workspace.id, team.id, Provider.GOOGLE_DRIVE, user_id=user.id)
    assert found is not None and found.id == drive_connection.id


def test_read_drive_file_rejected_when_resource_not_allow_listed(session):
    workspace, team, user, drive_connection, _ = _setup(session)
    channel_connection = ChannelConnection(team_id=team.id, connection_id=drive_connection.id, added_by_user_id=user.id)
    session.add(channel_connection)
    session.commit()
    # Assigned, but no resource allow-listed yet - must still be rejected.

    result = _execute_read_tool(session, workspace.id, "read_drive_file", {"file_id": "some-file-id"}, team_id=team.id, user_id=user.id)
    assert "error" in result
    assert "isn't authorized" in result["error"]


def test_read_drive_file_allowed_when_resource_allow_listed_stops_before_network_call(session):
    """Confirms the allow-list check passes (doesn't reject) once a matching
    resource_key exists - can't assert the real Drive fetch succeeds without
    a live token/network, but reaching past the permission check (instead of
    the "not authorized" error) proves the gate itself works correctly."""
    workspace, team, user, drive_connection, _ = _setup(session)
    channel_connection = ChannelConnection(team_id=team.id, connection_id=drive_connection.id, added_by_user_id=user.id)
    session.add(channel_connection)
    session.flush()
    session.add(ChannelConnectionResource(channel_connection_id=channel_connection.id, resource_key="some-file-id", resource_label="A File"))
    session.commit()

    with pytest.raises(Exception) as exc_info:
        # No real access token/network in this test env - failing past the
        # permission check (not on it) is exactly what this test verifies.
        _execute_read_tool(session, workspace.id, "read_drive_file", {"file_id": "some-file-id"}, team_id=team.id, user_id=user.id)
    assert "isn't authorized" not in str(exc_info.value)


def test_channel_with_no_connections_assigned_never_reaches_the_llm(session):
    """The short-circuit must fire before any LLM call - proven here by the
    fact this test has no Groq mock/network access at all and still passes."""
    workspace, team, user, _, _ = _setup(session)
    events = list(run_command_stream(session, workspace.id, "anything", team_id=team.id, user_id=user.id))

    assert len(events) == 1
    assert events[0]["type"] == "result"
    assert events[0]["status"] == "done"
    assert "doesn't have any Connections assigned" in events[0]["reply"]


def test_channel_with_no_connections_still_logs_history(session):
    workspace, team, user, _, _ = _setup(session)
    list(run_command_stream(session, workspace.id, "anything", team_id=team.id, user_id=user.id))

    entries = session.execute(select(ChannelAIHistoryEntry).where(ChannelAIHistoryEntry.team_id == team.id)).scalars().all()
    assert len(entries) == 1
    assert entries[0].command == "anything"


def test_plain_ai_command_never_logs_channel_history(session):
    """team_id=None must be a complete no-op for Channel AI history -
    nothing should get written for the original, non-Channel-scoped path."""
    from app.services.orchestrator import _maybe_log_channel_history

    _maybe_log_channel_history(session, None, None, "some command", "some reply")
    assert session.execute(select(ChannelAIHistoryEntry)).scalars().all() == []
