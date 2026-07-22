"""Phase 3: an admin-shared connection satisfies the requirement for everyone.

The correction this phase makes:

    "If an Admin has already explicitly shared a Workspace/Class/Group
    Connection, members should NOT be forced to reconnect that same service
    just to access the Workspace or Channels."

The old behaviour asked every member for their own Gmail before letting them
into a channel - and then never used it, because channel context is resolved
from *shared* connections only. So the gate bought the channel nothing while
pushing private mailboxes into a team workspace. These tests pin both halves:
sharing unblocks, and unblocking grants the member's own data to no one.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.channel_readiness import my_channel_readiness
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.shared_connection import (
    ChannelConnectionExclusion,
    SharedConnection,
    SharedScope,
)
from app.models.channel_connection import ChannelConnection
from app.models.channel_required_connection import ChannelRequiredConnection
from app.models.hierarchy import Group, WorkspaceClass
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.channel_authorization import resolve_channel_scope
from app.services.channel_readiness import ReadinessState, blocking_providers, member_checklist

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
    """One workspace, one class, one group, one channel, an admin and a member."""
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(workspace)
    session.flush()

    admin = User(email="admin@acme.test", name="Admin")
    member = User(email="member@acme.test", name="Member")
    session.add_all([admin, member])
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=admin.id, role=Role.EMPLOYEE))
    session.add(Membership(workspace_id=workspace.id, user_id=member.id, role=Role.EMPLOYEE))

    workspace_class = WorkspaceClass(workspace_id=workspace.id, name="Engineering", slug="eng")
    session.add(workspace_class)
    session.flush()
    group = Group(class_id=workspace_class.id, name="Platform", slug="platform")
    session.add(group)
    session.flush()

    team = Team(workspace_id=workspace.id, group_id=group.id, name="development", slug="dev")
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=admin.id, role=ChannelRole.CHANNEL_ADMIN))
    session.add(TeamMembership(team_id=team.id, user_id=member.id, role=ChannelRole.CHANNEL_MEMBER))

    # The admin's own Gmail - the account they will share as team context.
    admin_gmail = Connection(
        workspace_id=workspace.id, user_id=admin.id, provider=Provider.GMAIL,
        org="admin@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW - timedelta(minutes=5),
    )
    session.add(admin_gmail)

    # The channel requires Gmail.
    session.add(ChannelRequiredConnection(team_id=team.id, provider=Provider.GMAIL, is_required=True, added_by_user_id=admin.id))
    session.commit()

    return {
        "workspace": workspace, "class": workspace_class, "group": group, "team": team,
        "admin": admin, "member": member, "admin_gmail": admin_gmail,
    }


def _share(session, env, scope: SharedScope, scope_id, connection=None):
    shared = SharedConnection(
        scope_type=scope, scope_id=scope_id,
        connection_id=(connection or env["admin_gmail"]).id,
        added_by_user_id=env["admin"].id,
    )
    session.add(shared)
    session.commit()
    return shared


def _member_status(session, env):
    [status] = member_checklist(session, env["team"].id, env["workspace"].id, env["member"].id)
    return status


# --- the core correction ---------------------------------------------------


def test_without_sharing_the_member_is_still_blocked(session, env):
    """The baseline. Nothing shared, so the requirement is genuinely the
    member's to satisfy - Phase 3 must not unblock everyone unconditionally."""
    status = _member_status(session, env)

    assert status.provided_by is None
    assert status.blocks is True
    assert blocking_providers(session, env["team"].id, env["workspace"].id, env["member"].id) == [Provider.GMAIL]


@pytest.mark.parametrize(
    "scope_key, scope",
    [("workspace", SharedScope.WORKSPACE), ("class", SharedScope.CLASS), ("group", SharedScope.GROUP)],
)
def test_sharing_at_any_tier_unblocks_the_member(session, env, scope_key, scope):
    """Shared once by an admin, satisfied for every member beneath it - at
    whichever tier the admin chose."""
    scope_id = {"workspace": env["workspace"], "class": env["class"], "group": env["group"]}[scope_key].id
    _share(session, env, scope, scope_id)

    status = _member_status(session, env)

    assert status.provided_by == scope_key
    assert status.blocks is False
    assert blocking_providers(session, env["team"].id, env["workspace"].id, env["member"].id) == []


def test_a_channel_level_assignment_also_satisfies_it(session, env):
    session.add(ChannelConnection(
        team_id=env["team"].id, connection_id=env["admin_gmail"].id, added_by_user_id=env["admin"].id,
    ))
    session.commit()

    assert _member_status(session, env).provided_by == "channel"
    assert _member_status(session, env).blocks is False


def test_the_member_is_reported_as_not_connected_even_while_unblocked(session, env):
    """`state` and `blocks` answer different questions, and Phase 3 must not
    blur them: telling a member they are "connected" when they never
    authorized anything would be a lie about their own account."""
    _share(session, env, SharedScope.WORKSPACE, env["workspace"].id)

    status = _member_status(session, env)

    assert status.state == ReadinessState.NOT_CONNECTED
    assert status.account_label is None
    assert status.blocks is False


def test_the_readiness_route_reports_the_member_ready(session, env):
    _share(session, env, SharedScope.WORKSPACE, env["workspace"].id)

    result = my_channel_readiness(team_id=env["team"].id, session=session, user=env["member"])

    assert result.is_ready is True
    assert result.blocking_providers == []
    assert result.requirements[0].provided_by == "workspace"


# --- unblocking must not leak, widen, or fail open -------------------------


def test_being_unblocked_grants_the_member_no_access_to_the_admins_account(session, env):
    """The member is let in *because* the admin shared their mailbox as team
    context - which is exactly what the channel scope already exposed. The
    member gains no handle on the connection itself."""
    _share(session, env, SharedScope.WORKSPACE, env["workspace"].id)

    status = _member_status(session, env)

    # A tier name, not an account, an email, or an id.
    assert status.provided_by == "workspace"
    serialized = str(status.__dict__)
    assert "admin@acme.test" not in serialized
    assert str(env["admin_gmail"].id) not in serialized
    assert "encrypted_token" not in serialized


def test_the_members_own_connection_never_becomes_channel_context(session, env):
    """The heart of it: a personal connection is private. Connecting one
    changes the member's own checklist state and nothing else - the channel's
    authorized scope is unmoved."""
    before = resolve_channel_scope(session, env["team"].id)

    session.add(Connection(
        workspace_id=env["workspace"].id, user_id=env["member"].id, provider=Provider.GMAIL,
        org="member@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW,
    ))
    session.commit()

    after = resolve_channel_scope(session, env["team"].id)

    assert after["connections"] == before["connections"]
    assert after["labels"] == before["labels"]
    assert _member_status(session, env).state == ReadinessState.READY  # their own account, their own view


def test_sharing_in_a_sibling_group_does_not_unblock_this_channel(session, env):
    """Inheritance follows the channel's own branch. A connection shared to a
    group this channel does not belong to must leave it blocked."""
    sibling = Group(class_id=env["class"].id, name="Data", slug="data")
    session.add(sibling)
    session.flush()
    _share(session, env, SharedScope.GROUP, sibling.id)

    assert _member_status(session, env).provided_by is None
    assert _member_status(session, env).blocks is True


def test_sharing_in_another_workspace_does_not_unblock_this_channel(session, env):
    other = Workspace(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(other)
    session.flush()
    _share(session, env, SharedScope.WORKSPACE, other.id)

    assert _member_status(session, env).provided_by is None
    assert _member_status(session, env).blocks is True


def test_excluding_the_connection_here_puts_the_requirement_back_on_the_member(session, env):
    """Deny beats allow, all the way through to the checklist. If an admin
    excludes the shared Gmail from this channel, the channel no longer has it
    as context - so the member is genuinely blocked again, and must not be
    told someone else is covering it."""
    _share(session, env, SharedScope.WORKSPACE, env["workspace"].id)
    assert _member_status(session, env).blocks is False

    session.add(ChannelConnectionExclusion(
        team_id=env["team"].id, connection_id=env["admin_gmail"].id, excluded_by_user_id=env["admin"].id,
    ))
    session.commit()

    status = _member_status(session, env)
    assert status.provided_by is None
    assert status.blocks is True


def test_an_unshared_provider_still_blocks_alongside_a_shared_one(session, env):
    """Coverage is per provider, not a blanket pass. Sharing Gmail must not
    quietly satisfy a Drive requirement too."""
    session.add(ChannelRequiredConnection(
        team_id=env["team"].id, provider=Provider.GOOGLE_DRIVE, is_required=True, added_by_user_id=env["admin"].id,
    ))
    session.commit()
    _share(session, env, SharedScope.WORKSPACE, env["workspace"].id)

    by_provider = {s.provider: s for s in member_checklist(session, env["team"].id, env["workspace"].id, env["member"].id)}

    assert by_provider[Provider.GMAIL].blocks is False
    assert by_provider[Provider.GOOGLE_DRIVE].blocks is True
    assert blocking_providers(session, env["team"].id, env["workspace"].id, env["member"].id) == [Provider.GOOGLE_DRIVE]
