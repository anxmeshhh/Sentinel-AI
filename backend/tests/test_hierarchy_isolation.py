"""Phase 2y: Workspace -> Class -> Group -> Channel.

Ownership at every level, and isolation across every boundary. These are
written as attacks: each one takes a valid id from one part of the tree and
tries to use it somewhere it doesn't belong. A test that only proved the
happy path would pass just as well against a system with no scoping at all.

The expected answer to a cross-boundary id is **404, not 403** - saying
"exists, but not yours" confirms another tenant's org chart.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.hierarchy import (
    create_class_group,
    create_workspace_class,
    delete_class_group,
    delete_workspace_class,
    get_workspace_tree,
    list_class_groups,
    list_workspace_classes,
    update_class_group,
    update_workspace_class,
)
from app.api.routes.teams import create_team
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.team import ChannelPrivacy, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.hierarchy import ClassCreate, ClassUpdate, GroupCreate, GroupUpdate
from app.schemas.team import TeamCreate
from app.services.channel_management import ChannelConfigError, create_channel
from app.services.hierarchy import (
    HierarchyError,
    channel_path,
    create_group,
    get_group_in_workspace,
    workspace_id_for_group,
)


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


def _workspace(session, name, *, kind=WorkspaceKind.ORGANIZATION):
    workspace = Workspace(name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}", kind=kind)
    session.add(workspace)
    session.flush()
    return workspace


def _user(session, email, workspace, role=Role.ORG_ADMIN):
    user = User(email=email, name=email.split("@")[0])
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=role))
    session.commit()
    return user


@pytest.fixture
def env(session):
    """Two independent organizations, each with a full Class/Group/Channel
    chain - so every cross-tenant test has a real second tree to reach for
    rather than a fabricated id that would 404 for the wrong reason."""
    acme = _workspace(session, "Acme")
    globex = _workspace(session, "Globex")

    acme_admin = _user(session, "admin@acme.test", acme)
    acme_employee = _user(session, "employee@acme.test", acme, role=Role.EMPLOYEE)
    globex_admin = _user(session, "admin@globex.test", globex)

    dev = WorkspaceClass(workspace_id=acme.id, name="Development", slug="development")
    marketing = WorkspaceClass(workspace_id=acme.id, name="Marketing", slug="marketing")
    globex_class = WorkspaceClass(workspace_id=globex.id, name="Ops", slug="ops")
    session.add_all([dev, marketing, globex_class])
    session.flush()

    backend = Group(class_id=dev.id, name="Backend Team", slug="backend-team")
    frontend = Group(class_id=dev.id, name="Frontend Team", slug="frontend-team")
    campaigns = Group(class_id=marketing.id, name="Campaign Team", slug="campaign-team")
    globex_group = Group(class_id=globex_class.id, name="Infra", slug="infra")
    session.add_all([backend, frontend, campaigns, globex_group])
    session.commit()

    return {
        "acme": acme, "globex": globex,
        "acme_admin": acme_admin, "acme_employee": acme_employee, "globex_admin": globex_admin,
        "dev": dev, "marketing": marketing, "globex_class": globex_class,
        "backend": backend, "frontend": frontend, "campaigns": campaigns, "globex_group": globex_group,
    }


def _channel(session, env, group, name, *, creator=None, privacy=ChannelPrivacy.PUBLIC):
    workspace_id = workspace_id_for_group(session, group.id)
    return create_channel(
        session, workspace_id=workspace_id, group_id=group.id,
        creator=creator or env["acme_admin"], name=name, privacy=privacy,
    )


# === ownership ============================================================


def test_class_belongs_to_exactly_one_workspace(session, env):
    listed = list_workspace_classes(workspace_id=env["acme"].id, session=session, user=env["acme_admin"])
    assert {c.name for c in listed} == {"Development", "Marketing"}
    assert all(c.workspace_id == env["acme"].id for c in listed)

    # Globex's class is nowhere in Acme's list, and vice versa.
    globex_listed = list_workspace_classes(workspace_id=env["globex"].id, session=session, user=env["globex_admin"])
    assert {c.name for c in globex_listed} == {"Ops"}


def test_group_belongs_to_exactly_one_class(session, env):
    dev_groups = list_class_groups(
        workspace_id=env["acme"].id, class_id=env["dev"].id, session=session, user=env["acme_admin"]
    )
    assert {g.name for g in dev_groups} == {"Backend Team", "Frontend Team"}

    marketing_groups = list_class_groups(
        workspace_id=env["acme"].id, class_id=env["marketing"].id, session=session, user=env["acme_admin"]
    )
    assert {g.name for g in marketing_groups} == {"Campaign Team"}


def test_channel_belongs_to_exactly_one_group_and_derives_its_workspace(session, env):
    """The denormalization guarantee: `team.workspace_id` is not accepted
    from a caller, it is read off group -> class -> workspace. If these two
    could disagree, every authorization check that reads `team.workspace_id`
    would be asking about the wrong tenant."""
    channel = _channel(session, env, env["backend"], "api-development")

    assert channel.group_id == env["backend"].id
    assert channel.workspace_id == env["acme"].id
    assert channel.workspace_id == workspace_id_for_group(session, env["backend"].id)


def test_breadcrumb_resolves_the_full_chain(session, env):
    channel = _channel(session, env, env["backend"], "api-development")
    path = channel_path(session, channel)

    assert path["workspace_name"] == "Acme"
    assert path["class_name"] == "Development"
    assert path["group_name"] == "Backend Team"
    assert path["channel_name"] == "api-development"


# === cross-workspace isolation ===========================================


def test_cannot_read_another_workspaces_classes(session, env):
    with pytest.raises(HTTPException) as exc_info:
        list_workspace_classes(workspace_id=env["globex"].id, session=session, user=env["acme_admin"])
    assert exc_info.value.status_code == 404  # not 403 - don't confirm the workspace exists


def test_cannot_create_a_class_in_another_workspace(session, env):
    with pytest.raises(HTTPException) as exc_info:
        create_workspace_class(
            workspace_id=env["globex"].id, payload=ClassCreate(name="Trojan"),
            session=session, user=env["acme_admin"],
        )
    assert exc_info.value.status_code == 404


def test_cannot_address_another_workspaces_class_through_your_own_workspace(session, env):
    """ATTACK: the caller is a legitimate admin of Acme and supplies a real
    class id - Globex's. The workspace in the path is theirs, so a naive
    implementation that trusted the class id would happily edit it."""
    with pytest.raises(HTTPException) as exc_info:
        update_workspace_class(
            workspace_id=env["acme"].id, class_id=env["globex_class"].id,
            payload=ClassUpdate(name="Renamed"), session=session, user=env["acme_admin"],
        )
    assert exc_info.value.status_code == 404
    session.refresh(env["globex_class"])
    assert env["globex_class"].name == "Ops"  # untouched


def test_cannot_delete_another_workspaces_class(session, env):
    with pytest.raises(HTTPException) as exc_info:
        delete_workspace_class(
            workspace_id=env["acme"].id, class_id=env["globex_class"].id,
            session=session, user=env["acme_admin"],
        )
    assert exc_info.value.status_code == 404
    assert session.get(WorkspaceClass, env["globex_class"].id) is not None


def test_channel_cannot_be_created_in_another_workspaces_group(session, env):
    """ATTACK: the tenant boundary at channel-creation time. Acme's admin
    names Globex's group; the workspace comes from their own session."""
    with pytest.raises(ChannelConfigError):
        create_channel(
            session, workspace_id=env["acme"].id, group_id=env["globex_group"].id,
            creator=env["acme_admin"], name="smuggled",
        )


def test_group_lookup_is_scoped_by_workspace(session, env):
    assert get_group_in_workspace(session, env["acme"].id, env["backend"].id) is not None
    assert get_group_in_workspace(session, env["acme"].id, env["globex_group"].id) is None
    assert get_group_in_workspace(session, env["globex"].id, env["backend"].id) is None


# === cross-class isolation ===============================================


def test_cannot_address_a_group_through_the_wrong_class(session, env):
    """ATTACK: Backend Team lives in Development. Reaching it through
    Marketing - a class the caller legitimately administers - must fail, or
    the class in the path is decorative."""
    with pytest.raises(HTTPException) as exc_info:
        update_class_group(
            workspace_id=env["acme"].id, class_id=env["marketing"].id, group_id=env["backend"].id,
            payload=GroupUpdate(name="Hijacked"), session=session, user=env["acme_admin"],
        )
    assert exc_info.value.status_code == 404
    session.refresh(env["backend"])
    assert env["backend"].name == "Backend Team"


def test_cannot_delete_a_group_through_the_wrong_class(session, env):
    with pytest.raises(HTTPException) as exc_info:
        delete_class_group(
            workspace_id=env["acme"].id, class_id=env["marketing"].id, group_id=env["backend"].id,
            session=session, user=env["acme_admin"],
        )
    assert exc_info.value.status_code == 404
    assert session.get(Group, env["backend"].id) is not None


def test_listing_groups_of_a_foreign_class_is_refused(session, env):
    with pytest.raises(HTTPException) as exc_info:
        list_class_groups(
            workspace_id=env["acme"].id, class_id=env["globex_class"].id,
            session=session, user=env["acme_admin"],
        )
    assert exc_info.value.status_code == 404


def test_creating_a_group_under_a_foreign_class_is_refused(session, env):
    with pytest.raises(HTTPException) as exc_info:
        create_class_group(
            workspace_id=env["acme"].id, class_id=env["globex_class"].id,
            payload=GroupCreate(name="Trojan"), session=session, user=env["acme_admin"],
        )
    assert exc_info.value.status_code == 404


# === cross-group isolation ===============================================


def test_channels_do_not_leak_between_groups(session, env):
    _channel(session, env, env["backend"], "api-development")
    _channel(session, env, env["frontend"], "web")

    tree = get_workspace_tree(workspace_id=env["acme"].id, session=session, user=env["acme_admin"])
    dev = next(c for c in tree if c.name == "Development")
    backend = next(g for g in dev.groups if g.name == "Backend Team")
    frontend = next(g for g in dev.groups if g.name == "Frontend Team")

    assert [ch.name for ch in backend.channels] == ["api-development"]
    assert [ch.name for ch in frontend.channels] == ["web"]


def test_a_group_holding_channels_cannot_be_deleted(session, env):
    """Deleting a group would orphan its channels' connection assignments,
    requirements and AI history - one level below what was clicked."""
    _channel(session, env, env["backend"], "api-development")

    with pytest.raises(HTTPException) as exc_info:
        delete_class_group(
            workspace_id=env["acme"].id, class_id=env["dev"].id, group_id=env["backend"].id,
            session=session, user=env["acme_admin"],
        )
    assert exc_info.value.status_code == 400
    assert "still contains 1 channel" in exc_info.value.detail


def test_a_class_holding_groups_cannot_be_deleted(session, env):
    with pytest.raises(HTTPException) as exc_info:
        delete_workspace_class(
            workspace_id=env["acme"].id, class_id=env["dev"].id,
            session=session, user=env["acme_admin"],
        )
    assert exc_info.value.status_code == 400
    assert "still contains 2 groups" in exc_info.value.detail


# === cross-channel isolation (in the tree) ================================


def test_private_channels_stay_hidden_in_the_tree(session, env):
    """The tree must not become a second, laxer implementation of channel
    visibility - it reuses visible_teams_filter, and this pins that."""
    _channel(session, env, env["backend"], "secret", privacy=ChannelPrivacy.PRIVATE)
    _channel(session, env, env["backend"], "open", privacy=ChannelPrivacy.PUBLIC)

    tree = get_workspace_tree(workspace_id=env["acme"].id, session=session, user=env["acme_employee"])
    backend = next(g for c in tree for g in c.groups if g.name == "Backend Team")
    assert [ch.name for ch in backend.channels] == ["open"]

    # The workspace admin still sees both - Group Owner/Admin has full control.
    admin_tree = get_workspace_tree(workspace_id=env["acme"].id, session=session, user=env["acme_admin"])
    admin_backend = next(g for c in admin_tree for g in c.groups if g.name == "Backend Team")
    assert {ch.name for ch in admin_backend.channels} == {"secret", "open"}


def test_tree_is_refused_to_non_members(session, env):
    with pytest.raises(HTTPException) as exc_info:
        get_workspace_tree(workspace_id=env["globex"].id, session=session, user=env["acme_admin"])
    assert exc_info.value.status_code == 404


def test_empty_classes_and_groups_still_appear(session, env):
    """An admin who just created "Marketing" has to see it in order to put
    a group in it - filtering empties would make the create button lead
    nowhere."""
    tree = get_workspace_tree(workspace_id=env["acme"].id, session=session, user=env["acme_admin"])
    marketing = next(c for c in tree if c.name == "Marketing")
    assert [g.name for g in marketing.groups] == ["Campaign Team"]
    assert marketing.groups[0].channels == []


# === RBAC =================================================================


def test_plain_employee_cannot_create_a_class(session, env):
    with pytest.raises(HTTPException) as exc_info:
        create_workspace_class(
            workspace_id=env["acme"].id, payload=ClassCreate(name="Shadow IT"),
            session=session, user=env["acme_employee"],
        )
    assert exc_info.value.status_code == 403  # 403 not 404 - membership already proved the workspace is theirs


def test_plain_employee_cannot_create_a_group(session, env):
    with pytest.raises(HTTPException) as exc_info:
        create_class_group(
            workspace_id=env["acme"].id, class_id=env["dev"].id,
            payload=GroupCreate(name="Shadow Team"), session=session, user=env["acme_employee"],
        )
    assert exc_info.value.status_code == 403


def test_team_manager_can_create_groups_but_not_classes(session, env):
    """Groups are team structure - exactly what a team_manager is for.
    Classes are a workspace-wide concern and stay with workspace admins."""
    manager = _user(session, "manager@acme.test", env["acme"], role=Role.TEAM_MANAGER)

    group = create_class_group(
        workspace_id=env["acme"].id, class_id=env["dev"].id,
        payload=GroupCreate(name="Platform Team"), session=session, user=manager,
    )
    assert group.name == "Platform Team"

    with pytest.raises(HTTPException) as exc_info:
        create_workspace_class(
            workspace_id=env["acme"].id, payload=ClassCreate(name="Ops"), session=session, user=manager
        )
    assert exc_info.value.status_code == 403


def test_employee_can_read_the_hierarchy_they_belong_to(session, env):
    """Read access is workspace membership, not admin - you can't navigate
    to a channel inside a group you're not allowed to see the name of."""
    classes = list_workspace_classes(workspace_id=env["acme"].id, session=session, user=env["acme_employee"])
    assert {c.name for c in classes} == {"Development", "Marketing"}


# === Personal Workspace privacy ==========================================


def test_personal_workspace_cannot_contain_classes(session, env):
    """Phase 2x removed channels from Personal workspaces because a channel
    there makes the owner's private connections assignable. Classes and
    Groups are the same shared structure one level up."""
    personal = _workspace(session, "Personal", kind=WorkspaceKind.PERSONAL)
    owner = _user(session, "solo@personal.test", personal)

    with pytest.raises(HTTPException) as exc_info:
        create_workspace_class(
            workspace_id=personal.id, payload=ClassCreate(name="Mine"), session=session, user=owner
        )
    assert exc_info.value.status_code == 400


def test_personal_workspace_cannot_contain_groups(session, env):
    """Belt and braces: even if a Class somehow existed in a personal
    workspace, a Group must not be creatable under it."""
    personal = _workspace(session, "Personal", kind=WorkspaceKind.PERSONAL)
    owner = _user(session, "solo2@personal.test", personal)
    smuggled = WorkspaceClass(workspace_id=personal.id, name="Mine", slug="mine")
    session.add(smuggled)
    session.commit()

    with pytest.raises(HierarchyError):
        create_group(session, workspace_class=smuggled, creator=owner, name="Group")


def test_personal_workspace_channel_creation_still_refused(session, env):
    personal = _workspace(session, "Personal", kind=WorkspaceKind.PERSONAL)
    owner = _user(session, "solo3@personal.test", personal)

    with pytest.raises(HTTPException) as exc_info:
        create_team(
            workspace_id=personal.id,
            payload=TeamCreate(name="private", group_id=env["backend"].id),
            session=session, user=owner,
        )
    assert exc_info.value.status_code == 400


# === the hierarchy does not weaken per-user connection isolation ==========


def test_channels_in_the_same_group_do_not_share_a_members_connection(session, env):
    """Phase A's guarantee has to survive the new levels: connections belong
    to a user in a workspace, and being in the same Group grants nothing."""
    from app.repositories.connections import ConnectionRepository

    _channel(session, env, env["backend"], "api-development")
    _channel(session, env, env["backend"], "database")

    session.add(
        Connection(
            workspace_id=env["acme"].id, user_id=env["acme_admin"].id, provider=Provider.GMAIL,
            org="admin@acme.test", repo="gmail", encrypted_token="x",
        )
    )
    session.commit()

    repo = ConnectionRepository(session, env["acme"].id)
    assert repo.get_for_user(env["acme_admin"].id, Provider.GMAIL) is not None
    # A teammate in the same Group, same Class, same Workspace still gets nothing.
    assert repo.get_for_user(env["acme_employee"].id, Provider.GMAIL) is None


def test_required_connections_are_still_per_member_inside_the_hierarchy(session, env):
    from app.models.channel_required_connection import ChannelRequiredConnection
    from app.services.channel_readiness import blocking_providers

    channel = _channel(session, env, env["backend"], "api-development")
    session.add(TeamMembership(team_id=channel.id, user_id=env["acme_employee"].id))
    session.add(
        ChannelRequiredConnection(
            team_id=channel.id, provider=Provider.GMAIL, is_required=True,
            added_by_user_id=env["acme_admin"].id,
        )
    )
    session.add(
        Connection(
            workspace_id=env["acme"].id, user_id=env["acme_admin"].id, provider=Provider.GMAIL,
            org="admin@acme.test", repo="gmail", encrypted_token="x",
            # Synced, or the state would be `syncing` - which correctly
            # still blocks (Phase 2x-B), and would make this test pass for
            # the wrong reason.
            last_synced_at=datetime.now(timezone.utc),
        )
    )
    session.commit()

    assert blocking_providers(session, channel.id, env["acme"].id, env["acme_admin"].id) == []
    assert blocking_providers(session, channel.id, env["acme"].id, env["acme_employee"].id) == [Provider.GMAIL]
