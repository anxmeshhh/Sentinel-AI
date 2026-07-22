"""Phase 3: a personal connection enriches its owner's Sentinel and nobody else's.

The promise this phase makes to a member who opts in:

    "Personal Connections -> Completely optional -> Used only to enrich that
    individual's Private Sentinel, Personal + Unified Attention, and private
    cross-context intelligence -> Never exposed to Admins, Workspace,
    Classes, Groups, Channels, or other members."

That promise was not true before it. Two members of one team workspace share
an `attention_items` table, and neither read site could tell whose connection
produced a row: `/attention` returned every item in the workspace, and
`channel_briefing` matched on *provider*, so an admin sharing their mailbox
made "this channel may see Gmail" mean "this channel may see every mailbox
in this workspace". Items now carry `connection_id` and both sites gate on
it.

These tests are written from the attacker's side: given a member's private
mail sitting in the same workspace, can anyone else reach it?
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.attention import attention_context, get_attention
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import SharedConnection, SharedScope
from app.models.signal import Signal, SignalType
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.attention_engine import list_attention
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
    """One team workspace, an admin and a member, each with their own Gmail.

    The admin's is shared with the channel as team context; the member's is
    personal and shared with nobody. Both produce attention items into the
    same workspace-scoped table - which is precisely the condition the leak
    lived in.
    """
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(workspace)
    session.flush()

    admin = User(email="admin@acme.test", name="Admin")
    member = User(email="member@acme.test", name="Member")
    session.add_all([admin, member])
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=admin.id, role=Role.ORG_ADMIN))
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

    admin_gmail = Connection(
        workspace_id=workspace.id, user_id=admin.id, provider=Provider.GMAIL,
        org="admin@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW,
    )
    member_gmail = Connection(
        workspace_id=workspace.id, user_id=member.id, provider=Provider.GMAIL,
        org="member@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW,
    )
    session.add_all([admin_gmail, member_gmail])
    session.flush()

    # The admin shares theirs with the whole workspace. The member shares nothing.
    session.add(SharedConnection(
        scope_type=SharedScope.WORKSPACE, scope_id=workspace.id,
        connection_id=admin_gmail.id, added_by_user_id=admin.id,
    ))

    session.add_all([
        _item(workspace, admin_gmail, "email:team-1", "Contract renewal from the client"),
        _item(workspace, member_gmail, "email:private-1", "Your therapy appointment on Thursday"),
    ])
    session.commit()

    return {
        "workspace": workspace, "team": team, "admin": admin, "member": member,
        "admin_gmail": admin_gmail, "member_gmail": member_gmail,
    }


def _item(workspace, connection, dedupe_key, title):
    return AttentionItem(
        workspace_id=workspace.id, connection_id=connection.id, type=AttentionType.IMPORTANT_EMAIL,
        origin=AttentionOrigin.DETECTED, state=AttentionState.NEW, source_provider="gmail",
        dedupe_key=dedupe_key, title=title, why="starred, unread", priority=0.7,
    )


PRIVATE = "Your therapy appointment on Thursday"
TEAM = "Contract renewal from the client"


# --- the channel is shared context; a private mailbox is not ---------------


def test_a_shared_mailbox_does_not_drag_a_private_one_into_the_channel(session, env):
    """The leak, in one test. Gmail is authorized for this channel, and both
    items are Gmail - but only one comes from the connection that was
    actually shared."""
    titles = [i.title for i in build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"]]

    assert titles == [TEAM]
    assert PRIVATE not in titles


def test_provider_matching_would_have_leaked_it(session, env):
    """Why the gate is connection-based, kept executable rather than as a
    comment.

    This reconstructs the rule channel_briefing used before Phase 3 - "is the
    item's provider among the channel's authorized providers?" - and asserts
    it admits the member's private mail. If someone ever reasons that
    provider matching is equivalent and simpler, this fails and shows them
    the message it would have exposed.
    """
    from app.services.channel_authorization import resolve_channel_scope
    from app.services.channel_briefing import PROVIDER_BY_NAME

    scope = resolve_channel_scope(session, env["team"].id)
    private = session.query(AttentionItem).filter_by(title=PRIVATE).one()

    would_have_shown = PROVIDER_BY_NAME.get(private.source_provider or "") in scope["providers"]
    assert would_have_shown is True  # the old rule let it through
    assert private.connection_id not in scope["connections"]  # the new one does not


def test_the_channel_header_count_leaks_nothing_either(session, env):
    """The count is a second read site over the same data - a briefing that
    hides an item while the chip still counts it discloses its existence."""
    assert channel_pending_count(session, env["team"].id, env["workspace"].id) == 1


def test_an_item_with_no_recorded_connection_is_invisible_in_a_channel(session, env):
    """Fail-closed: provenance we cannot establish is not provenance we
    assume. A NULL is what a failed backfill leaves behind, and it must lose
    visibility rather than land in an arbitrary channel."""
    orphan = _item(env["workspace"], env["admin_gmail"], "email:orphan", "Unattributable")
    orphan.connection_id = None
    session.add(orphan)
    session.commit()

    titles = [i.title for i in build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"]]
    assert "Unattributable" not in titles


# --- the personal hub is personal ------------------------------------------


def test_each_member_sees_only_their_own_attention(session, env):
    admin_titles = [i.title for i in list_attention(session, env["workspace"].id, viewer_user_id=env["admin"].id)]
    member_titles = [i.title for i in list_attention(session, env["workspace"].id, viewer_user_id=env["member"].id)]

    assert admin_titles == [TEAM]
    assert member_titles == [PRIVATE]


def test_the_attention_route_does_not_hand_one_member_anothers_mail(session, env):
    """ATTACK: the admin is an ORG_ADMIN, the highest role in the workspace.
    Rank must not translate into reading a member's private mailbox."""
    items = get_attention(state=None, session=session, workspace_id=env["workspace"].id, user=env["admin"])

    titles = [i.title for i in items]
    assert titles == [TEAM]
    assert PRIVATE not in str([i.model_dump() for i in items])


def test_a_manual_reminder_belongs_to_its_author_alone(session, env):
    session.add(AttentionItem(
        workspace_id=env["workspace"].id, created_by_user_id=env["member"].id, connection_id=None,
        type=AttentionType.MANUAL, origin=AttentionOrigin.MANUAL, state=AttentionState.NEW,
        dedupe_key="manual:1", title="Call the clinic", why="you asked", priority=0.5,
    ))
    session.commit()

    admin_titles = [i.title for i in list_attention(session, env["workspace"].id, viewer_user_id=env["admin"].id)]
    member_titles = [i.title for i in list_attention(session, env["workspace"].id, viewer_user_id=env["member"].id)]

    assert "Call the clinic" not in admin_titles
    assert "Call the clinic" in member_titles


def test_the_context_counts_describe_the_callers_own_connections(session, env):
    """"Why is my list empty?" must be answered about the caller's own setup.
    Counting the workspace would both contradict their list and quantify a
    teammate's mail volume."""
    session.add_all([
        Signal(
            workspace_id=env["workspace"].id, connection_id=env["member_gmail"].id, type=SignalType.EMAIL,
            external_id=f"private-{n}", occurred_at=NOW - timedelta(hours=n), actor="x", payload={"label_ids": ["UNREAD"]},
        )
        for n in range(4)
    ])
    session.commit()

    as_admin = attention_context(session=session, workspace_id=env["workspace"].id, user=env["admin"])
    as_member = attention_context(session=session, workspace_id=env["workspace"].id, user=env["member"])

    assert as_admin["connection_count"] == 1  # their own Gmail, not the workspace's two
    assert as_admin["signals_seen"] == 0  # the member's mail volume is not the admin's business
    assert as_member["connection_count"] == 1
    assert as_member["signals_seen"] == 4


# --- opting in enriches the owner, and only the owner ----------------------


def test_connecting_privately_adds_to_your_own_list_and_no_one_elses(session, env):
    """The positive half of the promise: a personal connection is worth
    something to its owner. A second member connects, and their own list
    grows while everyone else's stays exactly as it was."""
    before_admin = [i.title for i in list_attention(session, env["workspace"].id, viewer_user_id=env["admin"].id)]

    session.add(_item(env["workspace"], env["member_gmail"], "email:private-2", "Bank statement ready"))
    session.commit()

    after_admin = [i.title for i in list_attention(session, env["workspace"].id, viewer_user_id=env["admin"].id)]
    after_member = [i.title for i in list_attention(session, env["workspace"].id, viewer_user_id=env["member"].id)]

    assert after_admin == before_admin
    assert "Bank statement ready" in after_member
    # And it reaches no shared surface.
    channel = [i.title for i in build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"]]
    assert "Bank statement ready" not in channel


def test_sharing_is_the_only_thing_that_moves_data_into_a_channel(session, env):
    """Before/after on one deliberate admin act, so the boundary is visible:
    nothing about the member's connection changes, and only the connection
    that was explicitly shared shows up."""
    session.query(SharedConnection).delete()
    session.commit()
    assert build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"] == []

    session.add(SharedConnection(
        scope_type=SharedScope.WORKSPACE, scope_id=env["workspace"].id,
        connection_id=env["admin_gmail"].id, added_by_user_id=env["admin"].id,
    ))
    session.commit()

    titles = [i.title for i in build_channel_briefing(session, env["team"].id, env["workspace"].id)["items"]]
    assert titles == [TEAM]
