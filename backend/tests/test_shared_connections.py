"""Phase 2z: connections shared at a Class or Group, inherited by channels.

The properties under test are inheritance (a channel sees what its Group and
Class share) and isolation (it never sees a sibling class's or another
group's shared connections). Written against the resolver every consumer now
delegates to, so a pass here means Feed/Briefing/Insights/Knowledge/AI all
inherit correctly.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.shared_connections import (
    add_class_resource,
    assign_class_connection,
    assign_group_connection,
    list_class_connections,
    unassign_class_connection,
)
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.channel_connection import ChannelConnectionCreate
from app.schemas.shared_connection import SharedConnectionCreate, SharedConnectionResourceCreate
from app.services.channel_authorization import (
    authorized_connections,
    connection_authorized_for_channel,
    resource_authorized_for_channel,
)


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
    ws = Workspace(name="Acme", slug=f"a-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    admin = User(email="admin@a.test", name="Admin")
    manager = User(email="mgr@a.test", name="Manager")
    member = User(email="member@a.test", name="Member")
    session.add_all([ws, admin, manager, member])
    session.flush()
    session.add_all([
        Membership(workspace_id=ws.id, user_id=admin.id, role=Role.ORG_ADMIN),
        Membership(workspace_id=ws.id, user_id=manager.id, role=Role.TEAM_MANAGER),
        Membership(workspace_id=ws.id, user_id=member.id, role=Role.EMPLOYEE),
    ])
    # Class -> two groups; group1 -> two channels; a second class for isolation.
    dev = WorkspaceClass(workspace_id=ws.id, name="Dev", slug="dev")
    other_class = WorkspaceClass(workspace_id=ws.id, name="Sales", slug="sales")
    session.add_all([dev, other_class])
    session.flush()
    backend = Group(class_id=dev.id, name="Backend", slug="be")
    frontend = Group(class_id=dev.id, name="Frontend", slug="fe")
    sales_group = Group(class_id=other_class.id, name="SalesTeam", slug="st")
    session.add_all([backend, frontend, sales_group])
    session.flush()
    api = Team(workspace_id=ws.id, group_id=backend.id, name="api", slug="api")
    db = Team(workspace_id=ws.id, group_id=backend.id, name="database", slug="database")
    web = Team(workspace_id=ws.id, group_id=frontend.id, name="web", slug="web")
    sales_chan = Team(workspace_id=ws.id, group_id=sales_group.id, name="leads", slug="leads")
    session.add_all([api, db, web, sales_chan])
    session.flush()
    for chan in (api, db, web, sales_chan):
        session.add(TeamMembership(team_id=chan.id, user_id=member.id, role=ChannelRole.CHANNEL_MEMBER))
    repo = Connection(workspace_id=ws.id, user_id=admin.id, provider=Provider.GITHUB, org="acme", repo="api", encrypted_token="x")
    drive = Connection(workspace_id=ws.id, user_id=admin.id, provider=Provider.GOOGLE_DRIVE, org="a@x", repo="drive", encrypted_token="x")
    session.add_all([repo, drive])
    session.commit()
    return locals()


# --- inheritance ----------------------------------------------------------


def test_class_connection_is_inherited_by_every_channel_in_the_class(session, env):
    assign_class_connection(
        workspace_id=env["ws"].id, class_id=env["dev"].id,
        payload=SharedConnectionCreate(connection_id=env["repo"].id), session=session, user=env["admin"],
    )
    # Both groups' channels in Dev inherit it; the Sales channel does not.
    assert connection_authorized_for_channel(session, env["api"].id, env["repo"].id)
    assert connection_authorized_for_channel(session, env["db"].id, env["repo"].id)
    assert connection_authorized_for_channel(session, env["web"].id, env["repo"].id)
    assert not connection_authorized_for_channel(session, env["sales_chan"].id, env["repo"].id)


def test_group_connection_is_inherited_only_within_that_group(session, env):
    assign_group_connection(
        workspace_id=env["ws"].id, class_id=env["dev"].id, group_id=env["backend"].id,
        payload=SharedConnectionCreate(connection_id=env["repo"].id), session=session, user=env["manager"],
    )
    # Backend's channels inherit; Frontend's channel (same class, other group) does not.
    assert connection_authorized_for_channel(session, env["api"].id, env["repo"].id)
    assert connection_authorized_for_channel(session, env["db"].id, env["repo"].id)
    assert not connection_authorized_for_channel(session, env["web"].id, env["repo"].id)


def test_source_label_reflects_the_tier(session, env):
    assign_class_connection(workspace_id=env["ws"].id, class_id=env["dev"].id,
                            payload=SharedConnectionCreate(connection_id=env["repo"].id), session=session, user=env["admin"])
    auth = authorized_connections(session, env["api"].id)[env["repo"].id]
    assert auth.source == "class"


def test_channel_assignment_overrides_the_source_label_but_merges_resources(session, env):
    """A connection shared at the Class AND assigned at the Channel shows as
    'channel' (most specific) and its resources are the union."""
    from app.api.routes.channel_connections import add_allowed_resource, assign_connection

    shared = assign_class_connection(workspace_id=env["ws"].id, class_id=env["dev"].id,
                                     payload=SharedConnectionCreate(connection_id=env["drive"].id), session=session, user=env["admin"])
    add_class_resource(workspace_id=env["ws"].id, class_id=env["dev"].id, shared_id=shared.id,
                       payload=SharedConnectionResourceCreate(resource_key="class-doc", resource_label="Class Doc"), session=session, user=env["admin"])
    cc = assign_connection(team_id=env["api"].id, payload=ChannelConnectionCreate(connection_id=env["drive"].id), session=session, user=env["admin"])
    add_allowed_resource(team_id=env["api"].id, channel_connection_id=cc.id,
                         payload=__import__("app.schemas.channel_connection", fromlist=["ChannelConnectionResourceCreate"]).ChannelConnectionResourceCreate(resource_key="chan-doc", resource_label="Chan Doc"),
                         session=session, user=env["admin"])

    auth = authorized_connections(session, env["api"].id)[env["drive"].id]
    assert auth.source == "channel"
    assert auth.resources == {"class-doc", "chan-doc"}  # merged across tiers


# --- resource fail-closed across tiers ------------------------------------


def test_shared_drive_resource_is_authorized_for_inheriting_channels(session, env):
    shared = assign_class_connection(workspace_id=env["ws"].id, class_id=env["dev"].id,
                                     payload=SharedConnectionCreate(connection_id=env["drive"].id), session=session, user=env["admin"])
    # Assigned but nothing allow-listed - fail closed.
    assert not resource_authorized_for_channel(session, env["api"].id, env["drive"].id, "course-materials")

    add_class_resource(workspace_id=env["ws"].id, class_id=env["dev"].id, shared_id=shared.id,
                       payload=SharedConnectionResourceCreate(resource_key="course-materials", resource_label="Course Materials"), session=session, user=env["admin"])
    # Now inheriting channels may see it; the sibling class's channel may not.
    assert resource_authorized_for_channel(session, env["api"].id, env["drive"].id, "course-materials")
    assert not resource_authorized_for_channel(session, env["sales_chan"].id, env["drive"].id, "course-materials")


# --- RBAC + tenant boundary ----------------------------------------------


def test_only_workspace_admin_manages_class_connections(session, env):
    # A team_manager can manage group connections but NOT class connections.
    with pytest.raises(HTTPException) as exc:
        assign_class_connection(workspace_id=env["ws"].id, class_id=env["dev"].id,
                                payload=SharedConnectionCreate(connection_id=env["repo"].id), session=session, user=env["manager"])
    assert exc.value.status_code == 403
    # A plain member can't either.
    with pytest.raises(HTTPException) as exc:
        assign_class_connection(workspace_id=env["ws"].id, class_id=env["dev"].id,
                                payload=SharedConnectionCreate(connection_id=env["repo"].id), session=session, user=env["member"])
    assert exc.value.status_code == 403


def test_cannot_share_a_connection_from_another_workspace(session, env):
    other_ws = Workspace(name="Other", slug="other", kind=WorkspaceKind.ORGANIZATION)
    session.add(other_ws)
    session.flush()
    foreign = Connection(workspace_id=other_ws.id, user_id=env["admin"].id, provider=Provider.GITHUB, org="x", repo="y", encrypted_token="x")
    session.add(foreign)
    session.commit()
    with pytest.raises(HTTPException) as exc:
        assign_class_connection(workspace_id=env["ws"].id, class_id=env["dev"].id,
                                payload=SharedConnectionCreate(connection_id=foreign.id), session=session, user=env["admin"])
    assert exc.value.status_code == 404


def test_unassigning_a_class_connection_revokes_inheritance(session, env):
    shared = assign_class_connection(workspace_id=env["ws"].id, class_id=env["dev"].id,
                                     payload=SharedConnectionCreate(connection_id=env["repo"].id), session=session, user=env["admin"])
    assert connection_authorized_for_channel(session, env["api"].id, env["repo"].id)
    unassign_class_connection(workspace_id=env["ws"].id, class_id=env["dev"].id, shared_id=shared.id, session=session, user=env["admin"])
    assert not connection_authorized_for_channel(session, env["api"].id, env["repo"].id)


def test_duplicate_share_at_same_scope_is_rejected(session, env):
    assign_class_connection(workspace_id=env["ws"].id, class_id=env["dev"].id,
                            payload=SharedConnectionCreate(connection_id=env["repo"].id), session=session, user=env["admin"])
    with pytest.raises(HTTPException) as exc:
        assign_class_connection(workspace_id=env["ws"].id, class_id=env["dev"].id,
                                payload=SharedConnectionCreate(connection_id=env["repo"].id), session=session, user=env["admin"])
    assert exc.value.status_code == 409
    # But the same connection CAN be shared at a different scope (a group).
    listed = list_class_connections(workspace_id=env["ws"].id, class_id=env["dev"].id, session=session, user=env["admin"])
    assert len(listed) == 1
