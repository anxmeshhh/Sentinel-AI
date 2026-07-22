"""Phase 2x-B: channel requirements + per-member readiness.

An admin says "this channel needs Gmail"; each member satisfies that with
their own account. The properties under test are therefore mostly about the
seam between those two facts: readiness must be computed per-person, an
admin must never gain a handle on a member's credentials, and every state
must be derived from real evidence rather than assumed.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.channel_readiness import (
    add_channel_requirement,
    channel_roster_readiness,
    list_channel_requirements,
    my_channel_readiness,
    remove_channel_requirement,
)
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.channel_readiness import ChannelRequirementCreate
from app.services.channel_readiness import ReadinessState, blocking_providers, member_checklist

from tests.hierarchy_helpers import make_group

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

    admin = User(email="admin@acme.test", name="Admin")
    member = User(email="member@acme.test", name="Member")
    session.add_all([admin, member])
    session.flush()
    # EMPLOYEE, not ORG_ADMIN: a workspace admin bypasses channel-role checks
    # entirely (see deps.require_channel_role), which would make the
    # admin-only tests below prove nothing.
    session.add(Membership(workspace_id=workspace.id, user_id=admin.id, role=Role.EMPLOYEE))
    session.add(Membership(workspace_id=workspace.id, user_id=member.id, role=Role.EMPLOYEE))

    team = Team(workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, name="development", slug="dev")
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=admin.id, role=ChannelRole.CHANNEL_ADMIN))
    session.add(TeamMembership(team_id=team.id, user_id=member.id, role=ChannelRole.CHANNEL_MEMBER))
    session.commit()

    return {"workspace": workspace, "team": team, "admin": admin, "member": member}


def _require(session, env, user, provider=Provider.GMAIL, is_required=True, reason=None):
    return add_channel_requirement(
        team_id=env["team"].id,
        payload=ChannelRequirementCreate(provider=provider, is_required=is_required, reason=reason),
        session=session, user=user,
    )


def _connect(session, env, user, provider=Provider.GMAIL, *, synced=True, revoked=False):
    connection = Connection(
        workspace_id=env["workspace"].id, user_id=user.id, provider=provider,
        org=f"{user.email}", repo=provider.value, encrypted_token="x",
        last_synced_at=NOW - timedelta(minutes=5) if synced else None,
        revoked_at=NOW if revoked else None,
    )
    session.add(connection)
    session.commit()
    return connection


# --- the requirement is about a provider, never about an account -----------


def test_a_requirement_names_a_provider_and_carries_no_account(session, env):
    """The structural guarantee: an admin declaring a requirement cannot
    attach their own connection to it, because the row has nowhere to put
    one. If this ever gains a connection_id, the admin's mailbox becomes
    the channel's mailbox."""
    out = _require(session, env, env["admin"], reason="so client replies land here")

    assert out.provider == "gmail"
    assert out.reason == "so client replies land here"
    assert not hasattr(out, "connection_id")


def test_only_a_channel_admin_can_declare_requirements(session, env):
    with pytest.raises(HTTPException) as exc_info:
        _require(session, env, env["member"])
    assert exc_info.value.status_code == 403


def test_any_member_can_read_the_requirements(session, env):
    """You cannot satisfy a requirement you are not allowed to see."""
    _require(session, env, env["admin"])
    listed = list_channel_requirements(team_id=env["team"].id, session=session, user=env["member"])
    assert [r.provider for r in listed] == ["gmail"]


def test_duplicate_requirement_is_rejected(session, env):
    _require(session, env, env["admin"])
    with pytest.raises(HTTPException) as exc_info:
        _require(session, env, env["admin"])
    assert exc_info.value.status_code == 409


# --- readiness is per-person ----------------------------------------------


def test_one_members_connection_does_not_make_another_member_ready(session, env):
    """The headline property. Before per-user connections this was
    structurally impossible to get right: a workspace held one Gmail, so
    either everyone was ready or nobody was."""
    _require(session, env, env["admin"])
    _connect(session, env, env["admin"])

    admin_view = my_channel_readiness(team_id=env["team"].id, session=session, user=env["admin"])
    member_view = my_channel_readiness(team_id=env["team"].id, session=session, user=env["member"])

    assert admin_view.is_ready is True
    assert member_view.is_ready is False
    assert member_view.blocking_providers == ["gmail"]


def test_readiness_is_always_about_the_caller(session, env):
    """There is no user_id parameter on this route by design - so there is
    no way to ask "is Bob ready?" through the member endpoint at all."""
    import inspect

    assert "user_id" not in inspect.signature(my_channel_readiness).parameters


def test_a_channel_with_no_requirements_blocks_nobody(session, env):
    result = my_channel_readiness(team_id=env["team"].id, session=session, user=env["member"])
    assert result.is_ready is True
    assert result.requirements == []


def test_optional_requirements_never_block(session, env):
    """If everything blocks, the checklist stops meaning anything."""
    _require(session, env, env["admin"], provider=Provider.GOOGLE_DRIVE, is_required=False)

    result = my_channel_readiness(team_id=env["team"].id, session=session, user=env["member"])
    assert result.is_ready is True
    assert result.blocking_providers == []
    assert result.requirements[0].state == "not_connected"  # still shown, just not blocking


def test_removing_a_requirement_unblocks_members(session, env):
    requirement = _require(session, env, env["admin"])
    assert blocking_providers(session, env["team"].id, env["workspace"].id, env["member"].id) == [Provider.GMAIL]

    remove_channel_requirement(
        team_id=env["team"].id, requirement_id=requirement.id, session=session, user=env["admin"]
    )
    assert blocking_providers(session, env["team"].id, env["workspace"].id, env["member"].id) == []


# --- every state is derived from evidence ---------------------------------


def test_state_is_not_connected_without_a_connection(session, env):
    _require(session, env, env["admin"])
    [status] = member_checklist(session, env["team"].id, env["workspace"].id, env["member"].id)
    assert status.state == ReadinessState.NOT_CONNECTED
    assert status.account_label is None


def test_state_is_syncing_until_the_first_sync_lands(session, env):
    """Connected but empty is a real, temporary state - reporting it as
    `ready` would make the first minutes after OAuth look broken."""
    _require(session, env, env["admin"])
    _connect(session, env, env["member"], synced=False)

    [status] = member_checklist(session, env["team"].id, env["workspace"].id, env["member"].id)
    assert status.state == ReadinessState.SYNCING
    assert status.blocks is True  # not usable yet


def test_state_is_ready_after_a_sync(session, env):
    _require(session, env, env["admin"])
    _connect(session, env, env["member"])

    [status] = member_checklist(session, env["team"].id, env["workspace"].id, env["member"].id)
    assert status.state == ReadinessState.READY
    assert status.blocks is False


def test_state_is_expired_only_when_a_refresh_actually_failed(session, env):
    """`expired` keys off revoked_at, which is written when Google refuses
    to mint a token - not off the stored access-token expiry, which is
    always about to lapse on a perfectly healthy connection."""
    _require(session, env, env["admin"])
    _connect(session, env, env["member"], revoked=True)

    [status] = member_checklist(session, env["team"].id, env["workspace"].id, env["member"].id)
    assert status.state == ReadinessState.EXPIRED
    assert status.blocks is True


def test_a_healthy_connection_is_never_reported_expired(session, env):
    """Guards the mistake this design exists to avoid: access tokens live
    ~1h and are refreshed silently, so any expiry check based on them would
    flag every working connection within the hour."""
    _require(session, env, env["admin"])
    connection = _connect(session, env, env["member"])
    connection.encrypted_token = "expires-long-ago-but-refreshable"
    session.commit()

    [status] = member_checklist(session, env["team"].id, env["workspace"].id, env["member"].id)
    assert status.state == ReadinessState.READY


# --- the admin roster leaks nothing ---------------------------------------


def test_admin_roster_shows_who_is_behind_without_exposing_credentials(session, env):
    _require(session, env, env["admin"])
    _connect(session, env, env["admin"])

    roster = channel_roster_readiness(team_id=env["team"].id, session=session, user=env["admin"])
    by_email = {r.email: r for r in roster}

    assert by_email["admin@acme.test"].is_ready is True
    assert by_email["member@acme.test"].is_ready is False

    # ATTACK: the roster is the one place an admin sees data derived from
    # other people's connections. It must carry no token and no connection
    # id - either would turn "who needs to set up?" into a credential
    # directory.
    serialized = str([r.model_dump() for r in roster])
    assert "encrypted_token" not in serialized
    assert "connection_id" not in serialized
    for entry in roster:
        for requirement in entry.requirements:
            assert set(requirement) == {"provider", "is_required", "state", "account_label"}


def test_plain_member_cannot_read_the_roster(session, env):
    _require(session, env, env["admin"])
    with pytest.raises(HTTPException) as exc_info:
        channel_roster_readiness(team_id=env["team"].id, session=session, user=env["member"])
    assert exc_info.value.status_code == 403


def test_an_empty_briefing_says_why_it_is_empty(session, env):
    """An empty channel briefing has two very different causes. "Nothing
    needs your attention" and "you never connected Gmail" must not render
    as the same blank panel - the second is fixable by the person reading
    it, and only if they're told."""
    from app.api.routes.channel_ai import channel_briefing

    _require(session, env, env["admin"])
    _connect(session, env, env["admin"])

    admin_briefing = channel_briefing(team_id=env["team"].id, session=session, user=env["admin"])
    member_briefing = channel_briefing(team_id=env["team"].id, session=session, user=env["member"])

    # Same channel, same moment, different answers - because the
    # requirement is satisfied per-person.
    assert admin_briefing.blocking_providers == []
    assert member_briefing.blocking_providers == ["gmail"]


def test_deleting_a_channel_removes_its_requirements(session, env):
    """Same failure mode as the channel-connection FK bug: a dependent
    table with no relationship() will fail the parent delete on MySQL while
    passing silently on SQLite."""
    from app.models.channel_required_connection import ChannelRequiredConnection
    from app.services.channel_management import delete_channel

    _require(session, env, env["admin"])
    team_id = env["team"].id

    delete_channel(session, env["team"])

    assert session.query(ChannelRequiredConnection).filter_by(team_id=team_id).count() == 0


def test_outsider_cannot_see_or_set_requirements(session, env):
    outsider = User(email="outsider@other.test", name="Outsider")
    session.add(outsider)
    session.commit()

    with pytest.raises(HTTPException) as exc_info:
        list_channel_requirements(team_id=env["team"].id, session=session, user=outsider)
    assert exc_info.value.status_code == 404  # not 403 - don't confirm existence


def test_live_query_providers_are_ready_immediately_not_stuck_syncing(session, env):
    """Google Drive is never ingested - files are searched live - so
    `last_synced_at` stays NULL forever. Reading that as "still syncing" left
    Drive permanently Syncing and permanently blocking setup: 3/3 was
    unreachable. Authorized means usable for a live-query provider."""
    _require(session, env, env["admin"], provider=Provider.GOOGLE_DRIVE)
    # synced=False mirrors reality: nothing ever sets last_synced_at here.
    _connect(session, env, env["member"], provider=Provider.GOOGLE_DRIVE, synced=False)

    [status] = member_checklist(session, env["team"].id, env["workspace"].id, env["member"].id)
    assert status.state == ReadinessState.READY
    assert status.blocks is False


def test_ingested_providers_still_show_syncing_until_first_sync(session, env):
    """The fix must not blanket-skip the syncing state - Gmail genuinely has
    a first ingestion to wait for."""
    _require(session, env, env["admin"], provider=Provider.GMAIL)
    _connect(session, env, env["member"], provider=Provider.GMAIL, synced=False)

    [status] = member_checklist(session, env["team"].id, env["workspace"].id, env["member"].id)
    assert status.state == ReadinessState.SYNCING
    assert status.blocks is True
