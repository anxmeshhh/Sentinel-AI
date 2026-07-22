"""Phase 3a: workspace-tier sharing + channel exclusions.

Two additions to the authorization model, tested as the properties that
make them safe rather than as happy paths:

- WORKSPACE is the broadest sharing tier. An admin shares once and every
  class/group/channel inherits - but only because someone deliberately
  shared it. Connecting a service still grants nothing anywhere, which is
  what keeps inheritance fail-closed.
- Exclusions are the narrowing half: one channel opts out of a connection
  it would otherwise inherit. Deny beats allow, unconditionally.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.channel_connections import assign_connection
from app.api.routes.shared_connections import (
    add_channel_exclusion,
    add_workspace_resource,
    assign_group_connection,
    assign_workspace_connection,
    remove_channel_exclusion,
)
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.channel_connection import ChannelConnectionCreate
from app.schemas.shared_connection import (
    ChannelExclusionCreate,
    SharedConnectionCreate,
    SharedConnectionResourceCreate,
)
from app.services.channel_authorization import (
    authorized_connections,
    connection_authorized_for_channel,
    resource_authorized_for_channel,
)
from app.services.channel_management import create_channel
from tests.hierarchy_helpers import make_group


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
    """One workspace: Class "Dev" -> groups Backend/Frontend -> channels.
    Plus a second workspace for cross-tenant checks."""
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
    dev = WorkspaceClass(workspace_id=ws.id, name="Dev", slug="dev")
    session.add(dev)
    session.flush()
    backend = Group(class_id=dev.id, name="Backend", slug="be")
    frontend = Group(class_id=dev.id, name="Frontend", slug="fe")
    session.add_all([backend, frontend])
    session.flush()
    api = Team(workspace_id=ws.id, group_id=backend.id, name="api", slug="api")
    db_chan = Team(workspace_id=ws.id, group_id=backend.id, name="database", slug="database")
    web = Team(workspace_id=ws.id, group_id=frontend.id, name="web", slug="web")
    session.add_all([api, db_chan, web])
    session.flush()
    for chan in (api, db_chan, web):
        session.add(TeamMembership(team_id=chan.id, user_id=member.id, role=ChannelRole.CHANNEL_MEMBER))
    repo = Connection(workspace_id=ws.id, user_id=admin.id, provider=Provider.GITHUB, org="acme", repo="api", encrypted_token="x")
    drive = Connection(workspace_id=ws.id, user_id=admin.id, provider=Provider.GOOGLE_DRIVE, org="a@x", repo="drive", encrypted_token="x")
    session.add_all([repo, drive])
    session.commit()
    return {
        "ws": ws, "admin": admin, "manager": manager, "member": member,
        "dev": dev, "backend": backend, "frontend": frontend,
        "api": api, "db": db_chan, "web": web, "repo": repo, "drive": drive,
    }


def _share_workspace(session, env, connection=None, user=None):
    return assign_workspace_connection(
        workspace_id=env["ws"].id,
        payload=SharedConnectionCreate(connection_id=(connection or env["repo"]).id),
        session=session, user=user or env["admin"],
    )


def _exclude(session, env, team_key, connection, user=None):
    return add_channel_exclusion(
        team_id=env[team_key].id,
        payload=ChannelExclusionCreate(connection_id=connection.id, reason="not relevant here"),
        session=session, user=user or env["admin"],
    )


# === 1. explicit workspace sharing and inheritance ========================


def test_workspace_share_is_inherited_by_every_channel(session, env):
    _share_workspace(session, env)
    for key in ("api", "db", "web"):
        assert connection_authorized_for_channel(session, env[key].id, env["repo"].id), key
    assert authorized_connections(session, env["api"].id)[env["repo"].id].source == "workspace"


def test_a_more_specific_tier_wins_the_source_label_and_merges_resources(session, env):
    """Shared at the workspace AND the group: authorized once, labelled by
    the closest tier."""
    _share_workspace(session, env)
    assign_group_connection(
        workspace_id=env["ws"].id, class_id=env["dev"].id, group_id=env["backend"].id,
        payload=SharedConnectionCreate(connection_id=env["repo"].id), session=session, user=env["admin"],
    )
    auth = authorized_connections(session, env["api"].id)
    assert auth[env["repo"].id].source == "group"       # most specific wins
    assert connection_authorized_for_channel(session, env["web"].id, env["repo"].id)  # still inherited at ws tier


# === 2. nothing is shared before an admin shares it =======================


def test_connecting_a_service_shares_it_nowhere(session, env):
    """The property that keeps inheritance fail-closed. Both connections
    exist in the workspace; neither is authorized anywhere."""
    assert authorized_connections(session, env["api"].id) == {}
    assert not connection_authorized_for_channel(session, env["api"].id, env["repo"].id)
    assert not connection_authorized_for_channel(session, env["api"].id, env["drive"].id)


def test_a_new_channel_inherits_only_what_was_already_shared(session, env):
    _share_workspace(session, env)  # repo only
    fresh = create_channel(
        session, workspace_id=env["ws"].id, group_id=env["backend"].id, creator=env["admin"], name="brand-new",
    )
    auth = authorized_connections(session, fresh.id)
    assert env["repo"].id in auth       # deliberately shared -> inherited
    assert env["drive"].id not in auth  # never shared -> still invisible


# === 3. cross-workspace isolation =========================================


def test_workspace_share_never_crosses_into_another_workspace(session, env):
    other_ws = Workspace(name="Other", slug=f"o-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(other_ws)
    session.flush()
    session.add(Membership(workspace_id=other_ws.id, user_id=env["admin"].id, role=Role.ORG_ADMIN))
    other_group = make_group(session, other_ws.id)
    session.commit()
    other_chan = create_channel(
        session, workspace_id=other_ws.id, group_id=other_group.id, creator=env["admin"], name="theirs",
    )

    _share_workspace(session, env)
    assert connection_authorized_for_channel(session, env["api"].id, env["repo"].id)
    assert not connection_authorized_for_channel(session, other_chan.id, env["repo"].id)


def test_cannot_share_a_connection_owned_by_another_workspace(session, env):
    other_ws = Workspace(name="Other", slug=f"o-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(other_ws)
    session.flush()
    foreign = Connection(workspace_id=other_ws.id, user_id=env["admin"].id, provider=Provider.GITHUB,
                         org="x", repo="y", encrypted_token="x")
    session.add(foreign)
    session.commit()

    with pytest.raises(HTTPException) as exc:
        _share_workspace(session, env, connection=foreign)
    assert exc.value.status_code == 404


# === 4. RBAC ==============================================================


def test_only_workspace_admins_share_at_the_workspace_tier(session, env):
    """The widest grant sits with the narrowest role set: a team_manager may
    share at a Group but not for the whole workspace."""
    for actor in ("manager", "member"):
        with pytest.raises(HTTPException) as exc:
            _share_workspace(session, env, user=env[actor])
        assert exc.value.status_code == 403, actor


def test_plain_member_cannot_exclude(session, env):
    _share_workspace(session, env)
    with pytest.raises(HTTPException) as exc:
        _exclude(session, env, "api", env["repo"], user=env["member"])
    assert exc.value.status_code == 403


# === 5. resource-level restriction still applies ==========================


def test_workspace_shared_drive_stays_fail_closed_until_allow_listed(session, env):
    shared = _share_workspace(session, env, connection=env["drive"])
    assert connection_authorized_for_channel(session, env["api"].id, env["drive"].id)
    # Connection authorized, but no file is - fail-closed survives inheritance.
    assert not resource_authorized_for_channel(session, env["api"].id, env["drive"].id, "course-materials")

    add_workspace_resource(
        workspace_id=env["ws"].id, shared_id=shared.id,
        payload=SharedConnectionResourceCreate(resource_key="course-materials", resource_label="Course Materials"),
        session=session, user=env["admin"],
    )
    assert resource_authorized_for_channel(session, env["api"].id, env["drive"].id, "course-materials")
    assert not resource_authorized_for_channel(session, env["api"].id, env["drive"].id, "some-other-doc")


# === 6. channel exclusion narrows correctly ===============================


def test_exclusion_blocks_inheritance_for_one_channel_only(session, env):
    _share_workspace(session, env)
    _exclude(session, env, "web", env["repo"])

    assert not connection_authorized_for_channel(session, env["web"].id, env["repo"].id)
    assert connection_authorized_for_channel(session, env["api"].id, env["repo"].id)
    assert connection_authorized_for_channel(session, env["db"].id, env["repo"].id)


def test_exclusion_beats_the_channels_own_explicit_assignment(session, env):
    """Deny beats allow, unconditionally - two opposite admin intentions
    must always resolve to the safe reading."""
    assign_connection(team_id=env["api"].id, payload=ChannelConnectionCreate(connection_id=env["repo"].id),
                      session=session, user=env["admin"])
    assert connection_authorized_for_channel(session, env["api"].id, env["repo"].id)

    _exclude(session, env, "api", env["repo"])
    assert not connection_authorized_for_channel(session, env["api"].id, env["repo"].id)


def test_exclusion_takes_resource_access_with_it(session, env):
    """Otherwise a Drive file would stay readable through a connection the
    channel is no longer authorized for."""
    shared = _share_workspace(session, env, connection=env["drive"])
    add_workspace_resource(
        workspace_id=env["ws"].id, shared_id=shared.id,
        payload=SharedConnectionResourceCreate(resource_key="secret-doc", resource_label="Secret"),
        session=session, user=env["admin"],
    )
    assert resource_authorized_for_channel(session, env["api"].id, env["drive"].id, "secret-doc")

    _exclude(session, env, "api", env["drive"])
    assert not resource_authorized_for_channel(session, env["api"].id, env["drive"].id, "secret-doc")


def test_lifting_an_exclusion_restores_inheritance(session, env):
    _share_workspace(session, env)
    exclusion = _exclude(session, env, "web", env["repo"])
    assert not connection_authorized_for_channel(session, env["web"].id, env["repo"].id)

    remove_channel_exclusion(team_id=env["web"].id, exclusion_id=exclusion.id, session=session, user=env["admin"])
    assert connection_authorized_for_channel(session, env["web"].id, env["repo"].id)


def test_cannot_exclude_a_connection_from_another_workspace(session, env):
    """A foreign id is meaningless here, and accepting it would let a caller
    probe for connection ids outside their tenant."""
    other_ws = Workspace(name="Other", slug=f"o-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(other_ws)
    session.flush()
    foreign = Connection(workspace_id=other_ws.id, user_id=env["admin"].id, provider=Provider.GITHUB,
                         org="x", repo="y", encrypted_token="x")
    session.add(foreign)
    session.commit()

    with pytest.raises(HTTPException) as exc:
        _exclude(session, env, "api", foreign)
    assert exc.value.status_code == 404


# === 7. personal connections never become shared ==========================


def test_personal_workspace_cannot_share_connections(session, env):
    """Personal stays private - sharing there would create exactly the
    surface the privacy model exists to prevent."""
    personal = Workspace(name="P", slug=f"p-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.PERSONAL)
    session.add(personal)
    session.flush()
    session.add(Membership(workspace_id=personal.id, user_id=env["admin"].id, role=Role.ORG_ADMIN))
    private = Connection(workspace_id=personal.id, user_id=env["admin"].id, provider=Provider.GMAIL,
                         org="me@gmail.com", repo="gmail", encrypted_token="secret")
    session.add(private)
    session.commit()

    with pytest.raises(HTTPException) as exc:
        assign_workspace_connection(
            workspace_id=personal.id, payload=SharedConnectionCreate(connection_id=private.id),
            session=session, user=env["admin"],
        )
    assert exc.value.status_code == 400


def test_a_personal_connection_is_never_authorized_in_any_channel(session, env):
    """Even with a workspace share in place, a connection living in the
    owner's Personal workspace is invisible to org channels."""
    personal = Workspace(name="P", slug=f"p-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.PERSONAL)
    session.add(personal)
    session.flush()
    private = Connection(workspace_id=personal.id, user_id=env["admin"].id, provider=Provider.GMAIL,
                         org="me@gmail.com", repo="gmail", encrypted_token="secret")
    session.add(private)
    session.commit()

    _share_workspace(session, env)
    for key in ("api", "db", "web"):
        assert not connection_authorized_for_channel(session, env[key].id, private.id), key
