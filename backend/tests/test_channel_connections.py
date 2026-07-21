"""Phase 2l: per-channel Connections + resource-level permissions.

The core property under test is fail-closed: assigning a Connection to a
Channel must grant zero resource access until a resource is explicitly
allow-listed, and only a Channel Admin (or Workspace admin) can manage any
of it.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.channel_connections import assign_connection, add_allowed_resource, list_team_connections, remove_allowed_resource, unassign_connection
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.channel_connection import ChannelConnectionCreate, ChannelConnectionResourceCreate
from app.services.channel_connections import is_resource_allowed


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


def _setup(session, admin_channel_role=ChannelRole.CHANNEL_ADMIN):
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(workspace)
    session.flush()

    admin = User(email="admin@acme.test", name="Admin")
    member = User(email="member@acme.test", name="Member")
    session.add_all([admin, member])
    session.flush()

    session.add(Membership(workspace_id=workspace.id, user_id=admin.id, role=Role.EMPLOYEE))
    session.add(Membership(workspace_id=workspace.id, user_id=member.id, role=Role.EMPLOYEE))

    team = Team(workspace_id=workspace.id, name="development", slug="dev")
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=admin.id, role=admin_channel_role))
    session.add(TeamMembership(team_id=team.id, user_id=member.id, role=ChannelRole.CHANNEL_MEMBER))

    connection = Connection(workspace_id=workspace.id, user_id=admin.id, provider=Provider.GITHUB, org="northwind", repo="checkout-service", encrypted_token="x")
    session.add(connection)
    session.commit()

    return workspace, team, admin, member, connection


def test_assigning_connection_grants_no_resource_access_by_default(session):
    """The core fail-closed property: assignment alone must not unlock
    anything until a resource is explicitly allow-listed."""
    _, team, admin, _, connection = _setup(session)
    payload = ChannelConnectionCreate(connection_id=connection.id)
    assign_connection(team_id=team.id, payload=payload, session=session, user=admin)

    assert is_resource_allowed(session, team.id, connection.id, "northwind/checkout-service") is False


def test_allow_listed_resource_becomes_accessible(session):
    _, team, admin, _, connection = _setup(session)
    payload = ChannelConnectionCreate(connection_id=connection.id)
    out = assign_connection(team_id=team.id, payload=payload, session=session, user=admin)

    add_allowed_resource(
        team_id=team.id, channel_connection_id=out.id,
        payload=ChannelConnectionResourceCreate(resource_key="northwind/checkout-service", resource_label="checkout-service"),
        session=session, user=admin,
    )

    assert is_resource_allowed(session, team.id, connection.id, "northwind/checkout-service") is True
    assert is_resource_allowed(session, team.id, connection.id, "northwind/some-other-repo") is False


def test_plain_channel_member_cannot_assign_connection(session):
    _, team, _, member, connection = _setup(session)
    payload = ChannelConnectionCreate(connection_id=connection.id)
    with pytest.raises(HTTPException) as exc_info:
        assign_connection(team_id=team.id, payload=payload, session=session, user=member)
    assert exc_info.value.status_code == 403


def test_plain_channel_member_can_view_assigned_connections(session):
    """Read access is for any channel member, not just admins - the spec's
    "authorized Channel members can use the capabilities" needs visibility
    even without management rights."""
    _, team, admin, member, connection = _setup(session)
    assign_connection(team_id=team.id, payload=ChannelConnectionCreate(connection_id=connection.id), session=session, user=admin)

    result = list_team_connections(team_id=team.id, session=session, user=member)
    assert len(result) == 1
    assert result[0].label == "northwind/checkout-service"


def test_cannot_assign_connection_from_a_different_workspace(session):
    _, team, admin, _, _ = _setup(session)
    other_workspace = Workspace(name="Other Co", slug="other-co", kind=WorkspaceKind.ORGANIZATION)
    session.add(other_workspace)
    session.flush()
    foreign_connection = Connection(workspace_id=other_workspace.id, user_id=admin.id, provider=Provider.GITHUB, org="foreign", repo="repo", encrypted_token="x")
    session.add(foreign_connection)
    session.commit()

    with pytest.raises(HTTPException) as exc_info:
        assign_connection(team_id=team.id, payload=ChannelConnectionCreate(connection_id=foreign_connection.id), session=session, user=admin)
    assert exc_info.value.status_code == 404


def test_unassigning_connection_cascades_its_resources(session):
    _, team, admin, _, connection = _setup(session)
    out = assign_connection(team_id=team.id, payload=ChannelConnectionCreate(connection_id=connection.id), session=session, user=admin)
    add_allowed_resource(
        team_id=team.id, channel_connection_id=out.id,
        payload=ChannelConnectionResourceCreate(resource_key="northwind/checkout-service", resource_label="checkout-service"),
        session=session, user=admin,
    )

    unassign_connection(team_id=team.id, channel_connection_id=out.id, session=session, user=admin)

    assert is_resource_allowed(session, team.id, connection.id, "northwind/checkout-service") is False
    assert list_team_connections(team_id=team.id, session=session, user=admin) == []


def test_plain_member_cannot_remove_resource(session):
    _, team, admin, member, connection = _setup(session)
    out = assign_connection(team_id=team.id, payload=ChannelConnectionCreate(connection_id=connection.id), session=session, user=admin)
    resource = add_allowed_resource(
        team_id=team.id, channel_connection_id=out.id,
        payload=ChannelConnectionResourceCreate(resource_key="northwind/checkout-service", resource_label="checkout-service"),
        session=session, user=admin,
    )

    with pytest.raises(HTTPException) as exc_info:
        remove_allowed_resource(team_id=team.id, channel_connection_id=out.id, resource_id=resource.id, session=session, user=member)
    assert exc_info.value.status_code == 403
