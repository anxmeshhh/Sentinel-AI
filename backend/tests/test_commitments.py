"""Commitment Intelligence: lifecycle, resolution, and the boundary.

The failure this module has to avoid is not missing a commitment - it is
asserting one that was never made, or announcing that something is done when
it isn't. So the tests lean on the two properties that make it defensible:
every transition is derived from a date or a source's own state field, and
resolution never comes from similarity.

Detection from prose is deliberately absent and there are no tests for it;
see the module docstring for the measurement that ruled it out.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.commitment import Commitment, CommitmentSource, CommitmentStatus
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import SharedConnection, SharedScope
from app.models.signal import Signal, SignalType
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.commitments import (
    create_manual_commitment,
    dismiss_commitment,
    list_commitments,
    refresh_commitments,
    refresh_commitments_for_workspace,
    reopen_commitment,
    resolve_commitment,
)
from app.services.investigation import channel_scope, personal_scope

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

    admin_github = Connection(workspace_id=workspace.id, user_id=admin.id, provider=Provider.GITHUB,
                              org="acme", repo="api", encrypted_token="x", last_synced_at=NOW)
    member_github = Connection(workspace_id=workspace.id, user_id=member.id, provider=Provider.GITHUB,
                               org="member", repo="private", encrypted_token="x", last_synced_at=NOW)
    session.add_all([admin_github, member_github])
    session.flush()
    session.add(SharedConnection(scope_type=SharedScope.WORKSPACE, scope_id=workspace.id,
                                 connection_id=admin_github.id, added_by_user_id=admin.id))
    session.commit()

    return {"workspace": workspace, "team": team, "admin": admin, "member": member,
            "admin_github": admin_github, "member_github": member_github}


def _personal(session, env, user=None):
    return personal_scope(session, env["workspace"].id, (user or env["admin"]).id)


def _issue(connection, external_id, title, *, assignee="rahul", closed=False, merged=False,
           updated_days_ago=0, due=None, signal_type=SignalType.ISSUE):
    payload = {"title": title, "assignee": assignee, "number": 12,
               "updated_at": (NOW - timedelta(days=updated_days_ago)).isoformat()}
    if closed:
        payload["closed_at"] = NOW.isoformat()
        payload["state"] = "closed"
    if merged:
        payload["merged_at"] = NOW.isoformat()
    if due:
        payload["due_on"] = due.isoformat()
    return Signal(
        workspace_id=connection.workspace_id, connection_id=connection.id, type=signal_type,
        external_id=external_id, actor="rahul", occurred_at=NOW - timedelta(days=2), payload=payload,
    )


def _manual(session, env, what="Send the report", *, due_at=None, scope=None, user=None):
    return create_manual_commitment(
        session, workspace_id=env["workspace"].id, scope=scope or _personal(session, env),
        what=what, due_at=due_at, user_id=(user or env["admin"]).id,
    )


# --- manual commitments ----------------------------------------------------


def test_a_stated_commitment_is_tracked_immediately(session, env):
    commitment = _manual(session, env, "Send the revised proposal", due_at=NOW + timedelta(days=5))

    assert commitment.source == CommitmentSource.MANUAL
    assert commitment.status == CommitmentStatus.PENDING
    assert commitment.what == "Send the revised proposal"


def test_a_commitment_with_no_date_stays_pending_forever(session, env):
    """"Someone should look at this eventually" is still worth remembering.
    It just never becomes urgent on its own."""
    _manual(session, env, "Tidy the onboarding docs", due_at=None)

    [commitment] = refresh_commitments(session, env["workspace"].id, _personal(session, env))
    assert commitment.status == CommitmentStatus.PENDING


def test_stating_the_same_thing_twice_makes_two_commitments(session, env):
    """Unlike a detected situation, a manual statement is its own evidence -
    saying it twice genuinely means two, and silently merging them would
    discard something a person deliberately wrote."""
    _manual(session, env, "Call the vendor")
    _manual(session, env, "Call the vendor")

    assert len(list_commitments(session, _personal(session, env))) == 2


# --- lifecycle -------------------------------------------------------------


def test_it_becomes_due_soon_inside_the_horizon(session, env):
    _manual(session, env, "Submit the form", due_at=NOW + timedelta(hours=12))

    [commitment] = refresh_commitments(session, env["workspace"].id, _personal(session, env))
    assert commitment.status == CommitmentStatus.DUE_SOON


def test_it_becomes_overdue_after_its_date(session, env):
    _manual(session, env, "Submit the form", due_at=NOW - timedelta(hours=6))

    [commitment] = refresh_commitments(session, env["workspace"].id, _personal(session, env))
    assert commitment.status == CommitmentStatus.OVERDUE


def test_a_manual_commitment_is_never_called_at_risk(session, env):
    """"At risk" is an observation about progress, and a manual commitment
    has no progress signal to read. Guessing would make the label meaningless
    on exactly the commitments people care most about."""
    _manual(session, env, "Draft the deck", due_at=NOW + timedelta(hours=6))

    [commitment] = refresh_commitments(session, env["workspace"].id, _personal(session, env))
    assert commitment.status == CommitmentStatus.DUE_SOON
    assert commitment.status != CommitmentStatus.AT_RISK


def test_overdue_sorts_above_everything_else(session, env):
    _manual(session, env, "Later thing", due_at=NOW + timedelta(days=10))
    _manual(session, env, "Missed thing", due_at=NOW - timedelta(days=1))
    _manual(session, env, "Soon thing", due_at=NOW + timedelta(hours=5))

    refresh_commitments(session, env["workspace"].id, _personal(session, env))
    ordered = [c.what for c in list_commitments(session, _personal(session, env))]

    assert ordered[0] == "Missed thing"


# --- resolution ------------------------------------------------------------


def test_a_person_can_mark_it_done_with_a_reason(session, env):
    commitment = _manual(session, env, "Send the report")

    resolved = resolve_commitment(session, commitment, reason="Sent it this morning")

    assert resolved.status == CommitmentStatus.RESOLVED
    assert resolved.resolved_at is not None
    assert resolved.resolution_reason == "Sent it this morning"
    assert list_commitments(session, _personal(session, env)) == []


def test_dismissed_is_not_the_same_as_resolved(session, env):
    """Collapsing them would make the record useless for the only question
    that matters later: do commitments here actually get met?"""
    commitment = _manual(session, env, "Maybe refactor this")

    dismissed = dismiss_commitment(session, commitment)

    assert dismissed.status == CommitmentStatus.DISMISSED
    assert dismissed.status != CommitmentStatus.RESOLVED


def test_reopening_returns_it_to_the_right_state(session, env):
    commitment = _manual(session, env, "Submit the form", due_at=NOW - timedelta(days=1))
    resolve_commitment(session, commitment, reason="done")

    reopened = reopen_commitment(session, commitment)

    assert reopened.status == CommitmentStatus.OVERDUE  # not blindly PENDING
    assert reopened.resolved_at is None


# --- tracked commitments (functionally tested; no real GitHub data yet) ----


def test_an_assigned_issue_becomes_a_tracked_commitment(session, env):
    session.add(_issue(env["admin_github"], "42", "Fix the login bug"))
    session.commit()

    [commitment] = refresh_commitments(session, env["workspace"].id, _personal(session, env))

    assert commitment.source == CommitmentSource.TRACKED
    assert commitment.what == "Fix the login bug"
    assert commitment.owner_label == "rahul"
    assert commitment.evidence[0]["kind"] == "issue"


def test_unassigned_work_is_not_a_commitment(session, env):
    """"Somebody should do this" is a wish. Tracking wishes is how a
    reminder list becomes noise nobody trusts."""
    session.add(_issue(env["admin_github"], "43", "Someone should look at flaky tests", assignee=None))
    session.commit()

    assert refresh_commitments(session, env["workspace"].id, _personal(session, env)) == []


def test_a_closed_issue_resolves_its_commitment_from_evidence(session, env):
    """Resolution as a fact read from the source, not an inference."""
    session.add(_issue(env["admin_github"], "44", "Fix the login bug"))
    session.commit()
    [commitment] = refresh_commitments(session, env["workspace"].id, _personal(session, env))
    assert commitment.status != CommitmentStatus.RESOLVED

    signal = session.execute(select(Signal).where(Signal.external_id == "44")).scalars().one()
    signal.payload = {**signal.payload, "closed_at": NOW.isoformat(), "state": "closed"}
    session.commit()

    assert refresh_commitments(session, env["workspace"].id, _personal(session, env)) == []
    stored = session.execute(select(Commitment)).scalars().one()
    assert stored.status == CommitmentStatus.RESOLVED
    assert "closed" in stored.resolution_reason


def test_a_merged_pr_resolves_its_commitment(session, env):
    session.add(_issue(env["admin_github"], "45", "Add rate limiting", merged=True, signal_type=SignalType.PR))
    session.commit()

    refresh_commitments(session, env["workspace"].id, _personal(session, env))

    stored = session.execute(select(Commitment)).scalars().one()
    assert stored.status == CommitmentStatus.RESOLVED
    assert "merged" in stored.resolution_reason


def test_a_similar_looking_signal_never_resolves_a_commitment(session, env):
    """The rule that keeps this honest: resolution comes from a commitment's
    own source, never from something that merely looks related. A commitment
    wrongly marked done defeats the entire point of tracking it."""
    session.add(_issue(env["admin_github"], "46", "Fix the login bug"))
    session.commit()
    refresh_commitments(session, env["workspace"].id, _personal(session, env))

    # A different, closed issue with an almost identical title.
    session.add(_issue(env["admin_github"], "47", "Fix the login bug (duplicate)", closed=True))
    session.commit()

    refresh_commitments(session, env["workspace"].id, _personal(session, env))
    original = session.execute(select(Commitment).where(Commitment.commitment_key == "issue:46")).scalars().one()
    assert original.status != CommitmentStatus.RESOLVED


def test_a_stalled_due_soon_commitment_is_flagged_at_risk(session, env):
    """AT_RISK requires an actual observation: due soon, and the source has
    shown no activity for days."""
    session.add(_issue(
        env["admin_github"], "48", "Ship the migration",
        due=NOW + timedelta(hours=12), updated_days_ago=6,
    ))
    session.commit()

    [commitment] = refresh_commitments(session, env["workspace"].id, _personal(session, env))
    assert commitment.status == CommitmentStatus.AT_RISK


def test_recent_activity_keeps_it_merely_due_soon(session, env):
    session.add(_issue(
        env["admin_github"], "49", "Ship the migration",
        due=NOW + timedelta(hours=12), updated_days_ago=0,
    ))
    session.commit()

    [commitment] = refresh_commitments(session, env["workspace"].id, _personal(session, env))
    assert commitment.status == CommitmentStatus.DUE_SOON


def test_re_detection_updates_rather_than_duplicates(session, env):
    session.add(_issue(env["admin_github"], "50", "Fix the login bug"))
    session.commit()

    first = refresh_commitments(session, env["workspace"].id, _personal(session, env))
    second = refresh_commitments(session, env["workspace"].id, _personal(session, env))

    assert len(first) == len(second) == 1
    assert first[0].id == second[0].id
    assert len(session.execute(select(Commitment)).scalars().all()) == 1


# --- the boundary ----------------------------------------------------------


def test_a_private_commitment_never_appears_in_the_channel(session, env):
    _manual(session, env, "Ask about my raise", scope=_personal(session, env, env["member"]), user=env["member"])

    channel = list_commitments(session, channel_scope(session, env["team"].id))

    assert channel == []


def test_a_channel_commitment_is_not_in_anyones_private_list(session, env):
    create_manual_commitment(
        session, workspace_id=env["workspace"].id, scope=channel_scope(session, env["team"].id),
        what="Ship the release", user_id=env["admin"].id,
    )

    assert list_commitments(session, _personal(session, env, env["admin"])) == []
    assert list_commitments(session, _personal(session, env, env["member"])) == []


def test_a_tracked_commitment_from_private_data_stays_private(session, env):
    """ATTACK: the member's own GitHub connection is not shared. Work assigned
    in it is their business, and must not become a team commitment."""
    session.add(_issue(env["member_github"], "99", "Fix my private side project"))
    session.commit()

    refresh_commitments_for_workspace(session, env["workspace"].id)

    channel = list_commitments(session, channel_scope(session, env["team"].id))
    member = list_commitments(session, _personal(session, env, env["member"]))

    assert all("private side project" not in c.what for c in channel)
    assert any("private side project" in c.what for c in member)


def test_the_shared_connection_does_produce_channel_commitments(session, env):
    session.add(_issue(env["admin_github"], "77", "Fix the shared login bug"))
    session.commit()

    refresh_commitments_for_workspace(session, env["workspace"].id)

    channel = list_commitments(session, channel_scope(session, env["team"].id))
    assert any("shared login bug" in c.what for c in channel)


def test_the_same_work_in_two_scopes_is_two_records(session, env):
    session.add(_issue(env["admin_github"], "88", "Fix the login bug"))
    session.commit()

    refresh_commitments_for_workspace(session, env["workspace"].id)

    rows = session.execute(select(Commitment).where(Commitment.commitment_key == "issue:88")).scalars().all()
    scopes = {r.scope_key for r in rows}

    assert len(rows) == 2
    assert any(s.startswith("personal:") for s in scopes)
    assert any(s.startswith("channel:") for s in scopes)


# --- background ------------------------------------------------------------


def test_the_background_pass_ages_a_manual_commitment_with_no_connections(session, env):
    """A person with nothing connected still has commitments, and they still
    have to go overdue - the scope enumeration must not be driven only by who
    owns a connection."""
    lonely = User(email="lonely@acme.test", name="Lonely")
    session.add(lonely)
    session.flush()
    session.add(Membership(workspace_id=env["workspace"].id, user_id=lonely.id, role=Role.EMPLOYEE))
    session.commit()

    scope = personal_scope(session, env["workspace"].id, lonely.id)
    assert scope.connection_ids == set()
    commitment = create_manual_commitment(
        session, workspace_id=env["workspace"].id, scope=scope,
        what="Renew the domain", due_at=NOW - timedelta(days=2), user_id=lonely.id,
    )
    commitment.status = CommitmentStatus.PENDING  # simulate a stale row
    session.commit()

    refresh_commitments_for_workspace(session, env["workspace"].id)

    session.refresh(commitment)
    assert commitment.status == CommitmentStatus.OVERDUE


def test_the_background_pass_costs_no_llm_calls(session, env):
    """Commitment Intelligence has no synthesis step at all. Asserted here so
    that a future 'let the model summarise this' cannot slip in unnoticed."""
    import app.services.commitments as module

    assert not hasattr(module, "LLMClient")
    assert "LLMClient" not in module.__dict__
