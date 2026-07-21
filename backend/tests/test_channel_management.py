"""Phase 2o: manual channel creation & management.

Exercises the shared channel_management service (the single path both the
manual UI and any future AI-assisted creation must go through) plus the
privacy/archive enforcement in the routes.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.routes.teams import create_team, get_team, join_team, list_teams
from app.models.base import Base
from app.models.channel_ai_history import ChannelAIHistoryEntry
from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
from app.models.connection import Connection, Provider
from app.models.team import ChannelPrivacy, ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.team import TeamCreate
from app.services.channel_management import (
    ChannelConfigError,
    create_channel,
    delete_channel,
    set_archived,
)

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

    owner = User(email="owner@acme.test", name="Owner")
    employee = User(email="employee@acme.test", name="Employee")
    session.add_all([owner, employee])
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=owner.id, role=Role.ORG_ADMIN))
    session.add(Membership(workspace_id=workspace.id, user_id=employee.id, role=Role.EMPLOYEE))
    session.commit()
    return workspace, owner, employee


def test_create_channel_full_config(session):
    workspace, owner, employee = _setup(session)
    connection = Connection(workspace_id=workspace.id, user_id=owner.id, provider=Provider.GITHUB, org="acme", repo="api", encrypted_token="x")
    session.add(connection)
    session.commit()

    team = create_channel(
session, workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, creator=owner,
        name="development", description="Dev team workspace", icon="🛠️", category="Teams",
        privacy=ChannelPrivacy.PRIVATE,
        member_user_ids=[employee.id], admin_user_ids=[], connection_ids=[connection.id],
    )

    assert team.description == "Dev team workspace"
    assert team.category == "Teams"
    assert team.privacy == ChannelPrivacy.PRIVATE
    memberships = {m.user_id: m.role for m in session.query(TeamMembership).filter_by(team_id=team.id)}
    assert memberships[owner.id] == ChannelRole.CHANNEL_ADMIN  # creator always admin
    assert memberships[employee.id] == ChannelRole.CHANNEL_MEMBER
    assert session.query(ChannelConnection).filter_by(team_id=team.id).count() == 1


def test_create_channel_rejects_non_workspace_member(session):
    workspace, owner, _ = _setup(session)
    outsider = User(email="outsider@other.test", name="Outsider")
    session.add(outsider)
    session.commit()

    with pytest.raises(ChannelConfigError):
        create_channel(
session, workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, creator=owner, name="dev", member_user_ids=[outsider.id])


def test_create_channel_rejects_foreign_connection(session):
    workspace, owner, _ = _setup(session)
    other = Workspace(name="Other", slug="other", kind=WorkspaceKind.ORGANIZATION)
    session.add(other)
    session.flush()
    foreign = Connection(workspace_id=other.id, user_id=owner.id, provider=Provider.GITHUB, org="them", repo="theirs", encrypted_token="x")
    session.add(foreign)
    session.commit()

    with pytest.raises(ChannelConfigError):
        create_channel(
session, workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, creator=owner, name="dev", connection_ids=[foreign.id])


def test_create_route_gated_to_admin_roles(session):
    """Spec: creating channels is a Group Owner/Admin capability - a plain
    employee gets 403 (behavior change from 2a's open creation, on the
    spec's explicit instruction)."""
    workspace, _, employee = _setup(session)
    with pytest.raises(HTTPException) as exc_info:
        create_team(
            workspace_id=workspace.id,
            payload=TeamCreate(name="rogue", group_id=make_group(session, workspace.id).id),
            session=session, user=employee,
        )
    assert exc_info.value.status_code == 403


def test_private_channel_hidden_from_non_member_list_and_lookup(session):
    workspace, owner, employee = _setup(session)
    team = create_channel(
session, workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, creator=owner, name="secret", privacy=ChannelPrivacy.PRIVATE)

    listed = list_teams(workspace_id=workspace.id, session=session, user=employee)
    assert all(t.id != team.id for t in listed)

    with pytest.raises(HTTPException) as exc_info:
        get_team(team_id=team.id, session=session, user=employee)
    assert exc_info.value.status_code == 404  # not 403 - don't confirm existence

    # The workspace admin still sees it (Group Owner/Admin has full control).
    assert any(t.id == team.id for t in list_teams(workspace_id=workspace.id, session=session, user=owner))


def test_invite_only_channel_visible_but_not_joinable(session):
    workspace, owner, employee = _setup(session)
    team = create_channel(
session, workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, creator=owner, name="managers", privacy=ChannelPrivacy.INVITE_ONLY)

    assert any(t.id == team.id for t in list_teams(workspace_id=workspace.id, session=session, user=employee))
    with pytest.raises(HTTPException) as exc_info:
        join_team(team_id=team.id, session=session, user=employee)
    assert exc_info.value.status_code == 403


def test_public_channel_join_unchanged(session):
    workspace, owner, employee = _setup(session)
    team = create_channel(
session, workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, creator=owner, name="general", privacy=ChannelPrivacy.PUBLIC)
    out = join_team(team_id=team.id, session=session, user=employee)
    assert out.is_member is True


def test_archived_channel_excluded_from_list_and_join(session):
    workspace, owner, employee = _setup(session)
    team = create_channel(
session, workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, creator=owner, name="old-project")
    set_archived(session, team, True)

    assert all(t.id != team.id for t in list_teams(workspace_id=workspace.id, session=session, user=owner))
    with pytest.raises(HTTPException) as exc_info:
        join_team(team_id=team.id, session=session, user=employee)
    assert exc_info.value.status_code == 400


def test_delete_channel_cascades_everything(session):
    workspace, owner, employee = _setup(session)
    connection = Connection(workspace_id=workspace.id, user_id=owner.id, provider=Provider.GITHUB, org="acme", repo="api", encrypted_token="x")
    session.add(connection)
    session.commit()
    team = create_channel(
session, workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, creator=owner, name="doomed",
        member_user_ids=[employee.id], connection_ids=[connection.id],
    )
    channel_connection = session.query(ChannelConnection).filter_by(team_id=team.id).one()
    session.add(ChannelConnectionResource(channel_connection_id=channel_connection.id, resource_key="acme/api", resource_label="api"))
    session.add(ChannelAIHistoryEntry(team_id=team.id, user_id=owner.id, command="hi", reply="hello"))
    session.commit()
    team_id = team.id

    delete_channel(session, team)

    assert session.get(Team, team_id) is None
    assert session.query(TeamMembership).filter_by(team_id=team_id).count() == 0
    assert session.query(ChannelConnection).filter_by(team_id=team_id).count() == 0
    assert session.query(ChannelConnectionResource).count() == 0
    assert session.query(ChannelAIHistoryEntry).filter_by(team_id=team_id).count() == 0
    # The workspace Connection itself must survive - it belongs to the
    # Group, the Channel only referenced it.
    assert session.execute(select(Connection).where(Connection.id == connection.id)).scalar_one_or_none() is not None


def test_admin_adds_existing_workspace_member_directly(session):
    """The entry path join_team's comment always promised for non-public
    channels ("an admin adding you") - now real. The workspace boundary is
    the hard check: a channel must never smuggle someone into a Group."""
    from app.api.routes.teams import add_team_member
    from app.schemas.team import TeamMemberAdd

    workspace, owner, employee = _setup(session)
    team = create_channel(
        session, workspace_id=workspace.id, group_id=make_group(session, workspace.id).id,
        creator=owner, name="private-ops", privacy=ChannelPrivacy.PRIVATE,
    )

    added = add_team_member(team_id=team.id, payload=TeamMemberAdd(user_id=employee.id), session=session, user=owner)
    assert added.channel_role == "channel_member"

    # An outsider isn't in the workspace: 404, not 403 - don't confirm the id.
    outsider = User(email="stranger@other.test", name="Stranger")
    session.add(outsider)
    session.commit()
    with pytest.raises(HTTPException) as exc_info:
        add_team_member(team_id=team.id, payload=TeamMemberAdd(user_id=outsider.id), session=session, user=owner)
    assert exc_info.value.status_code == 404

    # A plain channel member can't add people - admin capability only.
    with pytest.raises(HTTPException) as exc_info:
        add_team_member(team_id=team.id, payload=TeamMemberAdd(user_id=outsider.id), session=session, user=employee)
    assert exc_info.value.status_code == 403
