"""Proactive Intelligence: lifecycle, gating, and the boundary.

The risk with a feature that surfaces things unasked is not that it fails to
fire - it is that it fires too much, fires twice for one problem, keeps
shouting after the problem is over, or assembles a team's intelligence out
of somebody's private mail. So that is what these test.

The detection vocabulary itself was validated by measurement against the
real mailbox before it was written (5 genuine instances in 190 emails, no
false positives); see scripts/audit_proactive_jeopardy.py.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import SharedConnection, SharedScope
from app.models.signal import Signal, SignalType
from app.models.situation import Situation, SituationKind, SituationStatus
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.investigation import channel_scope, personal_scope
from app.services.proactive import MIN_IMPORTANCE, list_situations, refresh_situations

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
    session.add(Membership(workspace_id=workspace.id, user_id=admin.id, role=Role.ORG_ADMIN))
    session.add(Membership(workspace_id=workspace.id, user_id=member.id, role=Role.EMPLOYEE))

    klass = WorkspaceClass(workspace_id=workspace.id, name="Eng", slug="eng")
    session.add(klass)
    session.flush()
    group = Group(class_id=klass.id, name="Plat", slug="plat")
    session.add(group)
    session.flush()
    team = Team(workspace_id=workspace.id, group_id=group.id, name="dev", slug="dev")
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=admin.id, role=ChannelRole.CHANNEL_ADMIN))
    session.add(TeamMembership(team_id=team.id, user_id=member.id, role=ChannelRole.CHANNEL_MEMBER))

    admin_gmail = Connection(workspace_id=workspace.id, user_id=admin.id, provider=Provider.GMAIL,
                             org="admin@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW)
    member_gmail = Connection(workspace_id=workspace.id, user_id=member.id, provider=Provider.GMAIL,
                              org="member@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW)
    session.add_all([admin_gmail, member_gmail])
    session.flush()
    session.add(SharedConnection(scope_type=SharedScope.WORKSPACE, scope_id=workspace.id,
                                 connection_id=admin_gmail.id, added_by_user_id=admin.id))
    session.commit()

    return {"workspace": workspace, "team": team, "admin": admin, "member": member,
            "admin_gmail": admin_gmail, "member_gmail": member_gmail}


def _email(connection, external_id, subject, *, sender="alerts@vendor.example", days_ago=1):
    return Signal(
        workspace_id=connection.workspace_id, connection_id=connection.id, type=SignalType.EMAIL,
        external_id=external_id, actor=f"Vendor <{sender}>", occurred_at=NOW - timedelta(days=days_ago),
        payload={"subject": subject, "from": f"Vendor <{sender}>", "thread_id": external_id, "label_ids": ["UNREAD"]},
    )


def _personal(session, env, user=None):
    return personal_scope(session, env["workspace"].id, (user or env["admin"]).id)


def _run(session, env, scope=None):
    return refresh_situations(session, env["workspace"].id, scope or _personal(session, env))


# --- it detects the situation it was built for -----------------------------


def test_a_corroborated_service_failure_becomes_an_active_situation(session, env):
    """The shape validated on real data: a warning, then the thing happening."""
    session.add_all([
        _email(env["admin_gmail"], "s1", "Your Project QueryMind is going to be paused.", days_ago=3),
        _email(env["admin_gmail"], "s2", "Your Project QueryMind has been paused.", days_ago=2),
    ])
    session.commit()

    [situation] = _run(session, env)

    assert situation.kind == SituationKind.SERVICE_JEOPARDY
    assert situation.status == SituationStatus.ACTIVE  # corroborated
    assert situation.evidence_count == 2
    assert situation.importance >= 0.7


def test_evidence_is_real_rows_never_model_output(session, env):
    session.add_all([
        _email(env["admin_gmail"], "s1", "Your account will be deleted", days_ago=2),
    ])
    session.commit()

    [situation] = _run(session, env)

    for entry in situation.evidence:
        signal = session.get(Signal, uuid.UUID(entry["signal_id"]))
        assert signal is not None
        assert entry["title"] == signal.payload["subject"]


# --- it stays quiet -------------------------------------------------------


def test_an_ordinary_mailbox_produces_nothing_and_costs_nothing(session, env):
    """The most important test in the file. A feature that surfaces things
    unasked has to be silent when nothing is happening."""
    session.add_all([
        _email(env["admin_gmail"], "n1", "Weekly product newsletter"),
        _email(env["admin_gmail"], "n2", "Your invoice is ready"),
        _email(env["admin_gmail"], "n3", "Lunch tomorrow?"),
    ])
    session.commit()

    situations = _run(session, env)

    assert situations == []
    assert session.execute(select(Situation)).scalars().all() == []


def test_urgency_language_alone_does_not_qualify(session, env):
    """Marketing writes "act now" too. Only state changes to something you
    have count - the measurement that set this rule is in the module doc."""
    session.add_all([
        _email(env["admin_gmail"], "m1", "Act now — last chance to upgrade!"),
        _email(env["admin_gmail"], "m2", "Don't miss out: limited offer ending"),
    ])
    session.commit()

    assert _run(session, env) == []


def test_a_stale_singleton_is_suppressed(session, env):
    """A month-old notice that never came up again is history, not a
    developing situation. Verified on real data: three aged singletons were
    correctly rejected while the corroborated one surfaced."""
    session.add(_email(env["admin_gmail"], "old", "Service is being decommissioned", days_ago=30))
    session.commit()

    situations = _run(session, env)

    assert situations == []


def test_corroboration_is_what_lifts_it_over_the_bar(session, env):
    """Same vendor, same words, one extra message - and now it qualifies.
    This is the difference between a notice and a situation."""
    session.add(_email(env["admin_gmail"], "e1", "Your subscription is expiring", days_ago=20))
    session.commit()
    assert _run(session, env) == []  # single, aged: below the bar

    session.add(_email(env["admin_gmail"], "e2", "Your subscription has expired", days_ago=19))
    session.commit()

    [situation] = _run(session, env)
    assert situation.importance >= MIN_IMPORTANCE


# --- lifecycle: evolve, don't spam ----------------------------------------


def test_new_evidence_evolves_the_same_row_instead_of_adding_another(session, env):
    """The anti-notification-generator rule."""
    session.add(_email(env["admin_gmail"], "a1", "Your project is going to be paused", days_ago=3))
    session.commit()
    [first] = _run(session, env)
    assert first.status == SituationStatus.ACTIVE  # severe enough alone
    assert first.evidence_count == 1

    session.add(_email(env["admin_gmail"], "a2", "Your project has been paused", days_ago=1))
    session.commit()
    [second] = _run(session, env)

    assert second.id == first.id  # one row, not two
    assert second.evidence_count == 2
    assert len(session.execute(select(Situation)).scalars().all()) == 1


def test_a_repeat_run_with_no_new_evidence_spends_no_tokens(session, env):
    session.add_all([
        _email(env["admin_gmail"], "b1", "Your project is going to be paused", days_ago=3),
        _email(env["admin_gmail"], "b2", "Your project has been paused", days_ago=2),
    ])
    session.commit()

    [first] = _run(session, env)
    calls_after_first = first.llm_calls

    [second] = _run(session, env)

    assert second.id == first.id
    assert second.llm_calls == calls_after_first  # not re-synthesized


def test_a_resolution_message_closes_the_situation(session, env):
    """Sentinel should notice when the problem is over, deterministically,
    rather than warning about it forever."""
    session.add_all([
        _email(env["admin_gmail"], "c1", "Your project is going to be paused", days_ago=5),
        _email(env["admin_gmail"], "c2", "Your project has been paused", days_ago=4),
    ])
    session.commit()
    assert len(_run(session, env)) == 1

    session.add(_email(env["admin_gmail"], "c3", "Your project has been restored", days_ago=1))
    session.commit()

    assert _run(session, env) == []  # gone from the live list

    stored = session.execute(select(Situation)).scalars().one()
    assert stored.status == SituationStatus.RESOLVED
    assert stored.resolved_at is not None


def test_a_resolved_situation_stays_out_of_the_list(session, env):
    session.add_all([
        _email(env["admin_gmail"], "d1", "Your project has been paused", days_ago=4),
        _email(env["admin_gmail"], "d2", "Your project has been restored", days_ago=1),
    ])
    session.commit()
    _run(session, env)

    assert list_situations(session, _personal(session, env)) == []


# --- the boundary ---------------------------------------------------------


def test_a_channel_situation_is_never_built_from_private_mail(session, env):
    """ATTACK: the member's private mailbox contains a textbook situation.
    It is theirs. The channel must detect nothing from it."""
    session.add_all([
        _email(env["member_gmail"], "p1", "Your Project SECRET is going to be paused", days_ago=3),
        _email(env["member_gmail"], "p2", "Your Project SECRET has been paused", days_ago=2),
    ])
    session.commit()

    channel = refresh_situations(session, env["workspace"].id, channel_scope(session, env["team"].id))

    assert channel == []
    assert all("SECRET" not in s.title for s in session.execute(select(Situation)).scalars())


def test_the_member_sees_their_own_situation_privately(session, env):
    """The other half: it is genuinely useful to them."""
    session.add_all([
        _email(env["member_gmail"], "p1", "Your Project SECRET is going to be paused", days_ago=3),
        _email(env["member_gmail"], "p2", "Your Project SECRET has been paused", days_ago=2),
    ])
    session.commit()

    mine = refresh_situations(session, env["workspace"].id, _personal(session, env, env["member"]))
    theirs = refresh_situations(session, env["workspace"].id, _personal(session, env, env["admin"]))

    assert len(mine) == 1
    assert "SECRET" in mine[0].title
    assert theirs == []  # the admin, despite being ORG_ADMIN, sees nothing


def test_a_shared_connection_does_produce_channel_intelligence(session, env):
    """Not fail-closed to the point of uselessness: what an admin shared is
    exactly what the channel may reason over."""
    session.add_all([
        _email(env["admin_gmail"], "t1", "Your Project SHARED is going to be paused", days_ago=3),
        _email(env["admin_gmail"], "t2", "Your Project SHARED has been paused", days_ago=2),
    ])
    session.commit()

    channel = refresh_situations(session, env["workspace"].id, channel_scope(session, env["team"].id))

    assert len(channel) == 1
    assert "SHARED" in channel[0].title


def test_the_same_situation_in_two_scopes_is_two_rows(session, env):
    """Personal and channel intelligence are separate records even when they
    happen to observe the same thing - one row would mean one scope's view
    could be served to the other."""
    session.add_all([
        _email(env["admin_gmail"], "u1", "Your Project X is going to be paused", days_ago=3),
        _email(env["admin_gmail"], "u2", "Your Project X has been paused", days_ago=2),
    ])
    session.commit()

    [personal] = _run(session, env)
    [channel] = refresh_situations(session, env["workspace"].id, channel_scope(session, env["team"].id))

    assert personal.id != channel.id
    assert personal.scope_key.startswith("personal:")
    assert channel.scope_key.startswith("channel:")


def test_excluding_the_connection_ends_channel_situations(session, env):
    """Deny beats allow, inherited from the Phase 2 resolver rather than
    re-implemented here."""
    from app.models.shared_connection import ChannelConnectionExclusion

    session.add_all([
        _email(env["admin_gmail"], "v1", "Your Project Y is going to be paused", days_ago=3),
        _email(env["admin_gmail"], "v2", "Your Project Y has been paused", days_ago=2),
    ])
    session.commit()
    assert len(refresh_situations(session, env["workspace"].id, channel_scope(session, env["team"].id))) == 1

    session.add(ChannelConnectionExclusion(
        team_id=env["team"].id, connection_id=env["admin_gmail"].id, excluded_by_user_id=env["admin"].id,
    ))
    session.commit()

    assert refresh_situations(session, env["workspace"].id, channel_scope(session, env["team"].id)) == []


# --- the link into Investigate This ---------------------------------------


def test_the_investigation_link_is_offered_only_when_it_would_work(session, env):
    """Investigate This operates on attention items. A situation whose
    signals never produced one gets no button, rather than one that 404s.

    Both halves matter: on the real database this returns None (the Supabase
    emails were never flagged into attention), so without the positive case
    below the join would be untested.
    """
    from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
    from app.services.proactive import investigatable_item_id

    session.add_all([
        _email(env["admin_gmail"], "w1", "Your project is going to be paused", days_ago=3),
        _email(env["admin_gmail"], "w2", "Your project has been paused", days_ago=2),
    ])
    session.commit()
    [situation] = _run(session, env)

    assert investigatable_item_id(session, situation) is None  # no item exists yet

    item = AttentionItem(
        workspace_id=env["workspace"].id, connection_id=env["admin_gmail"].id,
        type=AttentionType.IMPORTANT_EMAIL, origin=AttentionOrigin.DETECTED, state=AttentionState.NEW,
        source_provider="gmail", dedupe_key="email:w2", title="Your project has been paused",
        why="starred", priority=0.8,
    )
    session.add(item)
    session.commit()

    assert investigatable_item_id(session, situation) == item.id


def test_a_scope_with_no_connections_detects_nothing(session, env):
    from app.services.investigation import Scope

    assert refresh_situations(session, env["workspace"].id, Scope(key="personal:nobody")) == []
