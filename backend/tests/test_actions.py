"""Agentic Actions: the guardrails, not the happy path.

This is the only module that changes things outside itself, so nearly every
test here is an attempt to make it do something it shouldn't - act without
approval, act twice, act across a scope boundary, act with a permission it
was never granted, or report success it cannot prove.

The external executor (Google Calendar) is stubbed. What is under test is
everything around it: the approval gate, the idempotency guarantee, the
verification step, and the refusal to claim success without confirmation.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.action import Action, ActionRisk, ActionStatus
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.commitment import Commitment, CommitmentStatus
from app.models.connection import Connection, Provider
from app.models.goal import Goal
from app.models.hierarchy import Group, WorkspaceClass
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services import action_registry
from app.services.action_registry import ActionRejected, ActionUnavailable
from app.services.actions import (
    NotAuthorized,
    approve_action,
    audit_trail,
    execute_action,
    propose_action,
    reject_action,
)

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
    outsider = User(email="outsider@acme.test", name="Outsider")
    session.add_all([admin, member, outsider])
    session.flush()
    for u, role in ((admin, Role.ORG_ADMIN), (member, Role.EMPLOYEE), (outsider, Role.EMPLOYEE)):
        session.add(Membership(workspace_id=workspace.id, user_id=u.id, role=role))

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
    session.commit()

    return {"workspace": workspace, "team": team, "admin": admin, "member": member, "outsider": outsider}


def _personal(env, user=None):
    return f"personal:{(user or env['admin']).id}"


def _channel(env):
    return f"channel:{env['team'].id}"


def _propose(session, env, action_type, params, *, scope=None, user=None, **kwargs):
    return propose_action(
        session,
        workspace_id=env["workspace"].id,
        scope_key=scope or _personal(env),
        action_type=action_type,
        params=params,
        user_id=(user or env["admin"]).id,
        **kwargs,
    )


@pytest.fixture
def stub_calendar(monkeypatch):
    """Stand in for Google. Records calls so double-execution is observable."""
    calls = {"created": [], "get": 0}

    def install(*, fail=False, missing_on_verify=False, raise_on_verify=False):
        def _execute(session, action):
            if fail:
                raise RuntimeError("Google said no")
            event_id = f"evt-{len(calls['created'])}"
            calls["created"].append(event_id)
            return {"event_id": event_id, "title": action.params["title"], "url": "https://cal/x",
                    "start": action.params["start"], "connection_id": str(uuid.uuid4())}

        def _verify(session, action, result):
            calls["get"] += 1
            if raise_on_verify:
                raise RuntimeError("network died")
            if missing_on_verify:
                return False, "The provider accepted the request but the event is not there"
            return True, "Read back from Google Calendar after creation"

        spec = action_registry.REGISTRY["calendar.create_event"]
        monkeypatch.setattr(spec, "execute", _execute)
        monkeypatch.setattr(spec, "verify", _verify)
        return calls

    return install


CAL_PARAMS = {
    "title": "Submit the report",
    "start": (NOW + timedelta(days=1)).isoformat(),
    "end": (NOW + timedelta(days=1, hours=1)).isoformat(),
}


# --- the allow-list --------------------------------------------------------


def test_an_unknown_action_type_cannot_be_proposed(session, env):
    """The line a prompt cannot talk its way past: if it is not in the
    registry, it does not exist."""
    with pytest.raises(ActionRejected, match="Unknown action type"):
        _propose(session, env, "shell.execute", {"cmd": "rm -rf /"})


def test_a_declared_but_unavailable_action_is_refused(session, env):
    """Declared so the shape is settled for a future connection - and refused
    until that connection exists, rather than quietly pretending."""
    with pytest.raises(ActionUnavailable, match="GitHub OAuth"):
        _propose(session, env, "github.create_issue", {"what": "Fix the bug"})


def test_sending_email_is_not_available_in_this_phase(session, env):
    with pytest.raises(ActionUnavailable):
        _propose(session, env, "email.send", {"subject": "hi", "body": "there"})


def test_malformed_parameters_are_rejected_before_anything_exists(session, env):
    """Model output is untrusted input. Pydantic decides what reaches an
    executor."""
    with pytest.raises(ActionRejected, match="Invalid parameters"):
        _propose(session, env, "commitment.create", {"what": ""})

    assert session.execute(select(Action)).scalars().all() == []


def test_an_action_cannot_run_in_a_scope_it_does_not_support(session, env):
    """Attention is personal by construction; a channel cannot snooze it."""
    with pytest.raises(ActionRejected, match="cannot be run in a channel context"):
        _propose(session, env, "attention.snooze", {"item_id": str(uuid.uuid4()), "hours": 4}, scope=_channel(env))


# --- approval --------------------------------------------------------------


def test_an_external_action_waits_for_approval(session, env, stub_calendar):
    stub_calendar()
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS)

    assert action.status == ActionStatus.AWAITING_APPROVAL
    assert action.risk == ActionRisk.MEDIUM
    assert action.approved_by_user_id is None


def test_an_unapproved_action_refuses_to_execute(session, env, stub_calendar):
    """The gate, tested directly rather than trusted."""
    calls = stub_calendar()
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS)

    with pytest.raises(ActionRejected, match="not been approved"):
        execute_action(session, action, env["admin"].id)

    assert calls["created"] == []  # nothing reached the provider


def test_a_low_risk_internal_action_needs_no_second_confirmation(session, env):
    """A reversible Sentinel-internal change is pre-approved by the request
    itself - and the record still names who that was, so the audit trail
    never has a blank approver."""
    action = _propose(session, env, "commitment.create", {"what": "Send the report"})

    assert action.status == ActionStatus.APPROVED
    assert action.approved_by_user_id == env["admin"].id
    assert action.approved_at is not None


def test_the_preview_is_stored_not_re_rendered(session, env, stub_calendar):
    """The record must prove what the user actually agreed to."""
    stub_calendar()
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS)

    assert action.preview["title"] == "Create a calendar event"
    assert action.preview["fields"]["Title"] == "Submit the report"
    assert "Google Calendar" in action.preview["effect"]


def test_rejecting_stops_it_permanently(session, env, stub_calendar):
    calls = stub_calendar()
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS)
    reject_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.REJECTED
    execute_action(session, action, env["admin"].id)  # terminal: no-op
    assert calls["created"] == []


# --- idempotency -----------------------------------------------------------


def test_proposing_the_same_thing_twice_yields_one_action(session, env, stub_calendar):
    stub_calendar()
    first = _propose(session, env, "calendar.create_event", CAL_PARAMS)
    second = _propose(session, env, "calendar.create_event", CAL_PARAMS)

    assert first.id == second.id
    assert len(session.execute(select(Action)).scalars().all()) == 1


def test_confirming_twice_creates_one_calendar_event(session, env, stub_calendar):
    """The headline guarantee. A double-clicked Confirm must not produce two
    events."""
    calls = stub_calendar()
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS)
    approve_action(session, action, env["admin"].id)

    execute_action(session, action, env["admin"].id)
    execute_action(session, action, env["admin"].id)

    assert len(calls["created"]) == 1
    assert action.status == ActionStatus.SUCCEEDED


def test_different_parameters_are_a_different_action(session, env, stub_calendar):
    stub_calendar()
    first = _propose(session, env, "calendar.create_event", CAL_PARAMS)
    second = _propose(session, env, "calendar.create_event", {**CAL_PARAMS, "title": "Something else"})

    assert first.id != second.id


# --- verification ----------------------------------------------------------


def test_success_is_only_claimed_after_reading_the_change_back(session, env, stub_calendar):
    calls = stub_calendar()
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS)
    approve_action(session, action, env["admin"].id)

    execute_action(session, action, env["admin"].id)

    assert calls["get"] == 1  # verification actually ran
    assert action.status == ActionStatus.SUCCEEDED
    assert "Read back" in action.verification


def test_an_unverifiable_result_is_UNKNOWN_not_SUCCEEDED(session, env, stub_calendar):
    """Ran, but could not be confirmed. Reporting failure would invite a
    duplicate; reporting success would be a lie."""
    stub_calendar(raise_on_verify=True)
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS)
    approve_action(session, action, env["admin"].id)

    execute_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.UNKNOWN
    assert action.status != ActionStatus.FAILED


def test_a_provider_that_accepted_but_produced_nothing_is_not_success(session, env, stub_calendar):
    stub_calendar(missing_on_verify=True)
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS)
    approve_action(session, action, env["admin"].id)

    execute_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.UNKNOWN


def test_a_provider_failure_is_recorded_honestly(session, env, stub_calendar):
    stub_calendar(fail=True)
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS)
    approve_action(session, action, env["admin"].id)

    execute_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.FAILED
    assert "Google said no" in action.error


def test_provider_errors_never_carry_credentials(session, env, monkeypatch):
    """Errors reach a screen. A leaked bearer token in one would be worse
    than the failure itself."""
    spec = action_registry.REGISTRY["calendar.create_event"]

    def _boom(session, action):
        raise RuntimeError("401 Unauthorized: Bearer ya29.SECRET-TOKEN-VALUE")

    monkeypatch.setattr(spec, "execute", _boom)
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS)
    approve_action(session, action, env["admin"].id)

    execute_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.FAILED
    assert "SECRET-TOKEN-VALUE" not in (action.error or "")
    assert "Bearer" not in (action.error or "")


# --- read access is not write access ---------------------------------------


def test_a_channel_member_cannot_run_an_admin_only_action(session, env, stub_calendar):
    """The central RBAC property. The member can *read* everything this
    channel is authorized for; writing to its calendar is a separate grant."""
    stub_calendar()

    with pytest.raises(NotAuthorized, match="channel admin"):
        _propose(session, env, "calendar.create_event", CAL_PARAMS,
                 scope=_channel(env), user=env["member"])


def test_a_channel_member_can_still_run_member_level_actions(session, env):
    """Not locked down to uselessness - recording a shared commitment is a
    member's job."""
    action = _propose(session, env, "commitment.create", {"what": "Ship the release"},
                      scope=_channel(env), user=env["member"])

    assert action.status == ActionStatus.APPROVED


def test_a_non_member_cannot_propose_into_a_channel(session, env):
    with pytest.raises(NotAuthorized, match="not a member"):
        _propose(session, env, "commitment.create", {"what": "Sneaky"},
                 scope=_channel(env), user=env["outsider"])


def test_nobody_can_act_in_another_persons_personal_scope(session, env):
    """ATTACK: the admin is an ORG_ADMIN. Rank does not grant access to
    someone else's private context."""
    with pytest.raises(NotAuthorized, match="your own personal context"):
        _propose(session, env, "commitment.create", {"what": "In their name"},
                 scope=_personal(env, env["member"]), user=env["admin"])


def test_approval_is_re_authorized_not_assumed(session, env, stub_calendar):
    """A proposal approved by the wrong person is not approved. The check
    runs again at approval time rather than trusting the proposal."""
    stub_calendar()
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS, scope=_channel(env))

    with pytest.raises(NotAuthorized):
        approve_action(session, action, env["member"].id)


def test_execution_is_re_authorized_too(session, env, stub_calendar):
    calls = stub_calendar()
    action = _propose(session, env, "calendar.create_event", CAL_PARAMS, scope=_channel(env))
    approve_action(session, action, env["admin"].id)

    with pytest.raises(NotAuthorized):
        execute_action(session, action, env["outsider"].id)

    assert calls["created"] == []


# --- cross-scope attacks ---------------------------------------------------


def test_a_channel_action_cannot_resolve_a_private_commitment(session, env):
    """ATTACK: the target belongs to a person, the action runs as a channel.
    The scope is re-checked at execution, not just at proposal."""
    from app.services.commitments import create_manual_commitment
    from app.services.investigation import Scope

    private = create_manual_commitment(
        session, workspace_id=env["workspace"].id, scope=Scope(key=_personal(env, env["member"])),
        what="My private promise", user_id=env["member"].id,
    )
    action = _propose(session, env, "commitment.resolve", {"commitment_id": str(private.id)},
                      scope=_channel(env))
    approve_action(session, action, env["admin"].id)

    execute_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.FAILED
    assert "different context" in action.error
    session.refresh(private)
    assert private.status != CommitmentStatus.RESOLVED


def test_snoozing_cannot_target_someone_elses_attention_item(session, env):
    """ATTACK: attention items carry no scope_key, so ownership is resolved
    through the connection that produced them."""
    connection = Connection(
        workspace_id=env["workspace"].id, user_id=env["member"].id, provider=Provider.GMAIL,
        org="member@acme.test", repo="gmail", encrypted_token="x",
    )
    session.add(connection)
    session.flush()
    item = AttentionItem(
        workspace_id=env["workspace"].id, connection_id=connection.id, type=AttentionType.IMPORTANT_EMAIL,
        origin=AttentionOrigin.DETECTED, state=AttentionState.NEW, source_provider="gmail",
        dedupe_key="email:theirs", title="Their private mail", why="starred", priority=0.7,
    )
    session.add(item)
    session.commit()

    action = _propose(session, env, "attention.snooze", {"item_id": str(item.id), "hours": 4})
    execute_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.FAILED
    assert "does not belong to you" in action.error
    session.refresh(item)
    assert item.state == AttentionState.NEW


def test_a_created_commitment_lands_in_the_acting_scope(session, env):
    """Verification is not a formality: it re-reads the row and checks the
    scope it actually landed in."""
    action = _propose(session, env, "commitment.create", {"what": "Ship the release"}, scope=_channel(env))
    approve_action(session, action, env["admin"].id)
    execute_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.SUCCEEDED
    commitment = session.get(Commitment, uuid.UUID(action.result["commitment_id"]))
    assert commitment.scope_key == _channel(env)


# --- real internal actions end to end --------------------------------------


def test_creating_a_goal_through_an_action_works_and_is_verified(session, env):
    action = _propose(session, env, "goal.create", {"title": "Launch Product V2"})
    execute_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.SUCCEEDED
    goal = session.get(Goal, uuid.UUID(action.result["goal_id"]))
    assert goal.title == "Launch Product V2"
    assert "Read back" in action.verification


def test_resolving_a_commitment_through_an_action(session, env):
    from app.services.commitments import create_manual_commitment
    from app.services.investigation import Scope

    commitment = create_manual_commitment(
        session, workspace_id=env["workspace"].id, scope=Scope(key=_personal(env)),
        what="Send the report", user_id=env["admin"].id,
    )
    action = _propose(session, env, "commitment.resolve", {"commitment_id": str(commitment.id)})
    execute_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.SUCCEEDED
    session.refresh(commitment)
    assert commitment.status == CommitmentStatus.RESOLVED


def test_a_draft_is_never_sent(session, env):
    """The line this phase does not cross."""
    action = _propose(session, env, "email.draft", {"subject": "Update", "body": "Here is the update."})
    execute_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.SUCCEEDED
    assert action.result["sent"] is False
    assert "nothing was sent" in action.verification


# --- provenance and audit --------------------------------------------------


def test_an_action_records_the_intelligence_that_suggested_it(session, env):
    """Actions emerge from existing intelligence rather than a free-floating
    agent, so the record points back at what made it seem sensible."""
    source = uuid.uuid4()
    action = _propose(
        session, env, "commitment.create", {"what": "Fix the deploy"},
        reason="The goal is blocked and this is the recommended next step",
        source_kind="goal", source_id=source,
    )

    assert action.source_kind == "goal"
    assert action.source_id == source
    assert "recommended next step" in action.reason


def test_the_audit_trail_shows_only_things_that_ran(session, env):
    executed = _propose(session, env, "commitment.create", {"what": "Did happen"})
    execute_action(session, executed, env["admin"].id)
    _propose(session, env, "commitment.create", {"what": "Never ran"})

    trail = audit_trail(session, env["workspace"].id)

    assert [a.id for a in trail] == [executed.id]
    entry = trail[0]
    assert entry.requested_by_user_id == env["admin"].id
    assert entry.approved_by_user_id is not None
    assert entry.executed_at is not None
    assert entry.verification


def test_the_audit_trail_carries_no_secrets(session, env):
    action = _propose(session, env, "email.draft", {"subject": "Wire transfer", "body": "Account 8891, code 4471."})
    execute_action(session, action, env["admin"].id)

    serialized = str([a.result for a in audit_trail(session, env["workspace"].id)])
    assert "8891" not in serialized
    assert "4471" not in serialized  # the body is counted, never copied
