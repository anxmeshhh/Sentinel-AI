"""The five Module 10 enhancements, tested as guardrails.

Natural language, attendees, bounded autonomy, compensation and audit each
widen what Sentinel can do, so each one gets tested from the side of what it
must still refuse. The model is stubbed throughout: what is under test is the
machinery around it, which is the only part that decides anything.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - registers every table on Base.metadata before create_all
from app.models.action import Action, ActionRisk, ActionStatus
from app.models.action_policy import ActionPolicy
from app.models.base import Base
from app.models.commitment import Commitment, CommitmentStatus
from app.models.goal import Goal, GoalHealth
from app.models.hierarchy import Group, WorkspaceClass
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services import action_intent, action_registry
from app.services.action_intent import IntentUnclear, propose_from_text
from app.services.action_policy import PolicyDenied, autonomy_allows, set_policy
from app.services.action_registry import ActionRejected, Reversibility
from app.services.actions import (
    NotAuthorized,
    approve_action,
    execute_action,
    propose_action,
    undo_action,
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
    session.commit()
    return {"workspace": workspace, "team": team, "admin": admin, "member": member}


def _personal(env, user=None):
    return f"personal:{(user or env['admin']).id}"


def _propose(session, env, action_type, params, *, scope=None, user=None, **kw):
    return propose_action(
        session, workspace_id=env["workspace"].id, scope_key=scope or _personal(env),
        action_type=action_type, params=params, user_id=(user or env["admin"]).id, **kw,
    )


@pytest.fixture
def stub_intent(monkeypatch):
    """Script the model's structured output."""
    def install(answer):
        class _Client:
            def complete_json(self, **_kwargs):
                return answer

        monkeypatch.setattr(action_intent, "LLMClient", _Client)
    return install


CAL = {
    "title": "Standup",
    "start": (NOW + timedelta(days=1)).isoformat(),
    "end": (NOW + timedelta(days=1, hours=1)).isoformat(),
}


# --- 1. natural language ---------------------------------------------------


def test_plain_text_becomes_a_proposal_not_an_act(session, env, stub_intent):
    """The whole safety story: text in, a proposal out, nothing executed."""
    stub_intent({
        "found": True, "action_type": "commitment.create",
        "params": {"what": "Review the deck"},
        "interpretation": "You want to track reviewing the deck",
    })

    proposed = propose_from_text(
        session, text="remind me to review the deck", workspace_id=env["workspace"].id,
        scope_key=_personal(env), user_id=env["admin"].id,
    )

    assert proposed.action.status != ActionStatus.SUCCEEDED
    assert proposed.action.executed_at is None
    assert proposed.action.source_kind == "natural_language"
    assert "reviewing the deck" in proposed.interpretation


def test_an_external_action_from_text_still_waits_for_approval(session, env, stub_intent):
    stub_intent({"found": True, "action_type": "calendar.create_event", "params": CAL,
                 "interpretation": "Create a standup"})

    proposed = propose_from_text(
        session, text="make a standup tomorrow", workspace_id=env["workspace"].id,
        scope_key=_personal(env), user_id=env["admin"].id,
    )

    assert proposed.action.status == ActionStatus.AWAITING_APPROVAL


def test_a_model_naming_an_action_that_does_not_exist_is_refused(session, env, stub_intent):
    """ATTACK: the model invents a tool. The registry is the boundary, not
    the prompt."""
    stub_intent({"found": True, "action_type": "shell.execute", "params": {"cmd": "rm -rf /"},
                 "interpretation": "Delete everything"})

    with pytest.raises(IntentUnclear, match="cannot do that"):
        propose_from_text(
            session, text="delete everything", workspace_id=env["workspace"].id,
            scope_key=_personal(env), user_id=env["admin"].id,
        )

    assert session.execute(select(Action)).scalars().all() == []


def test_a_model_naming_an_unavailable_action_is_refused(session, env, stub_intent):
    stub_intent({"found": True, "action_type": "email.send",
                 "params": {"subject": "hi", "body": "there"}, "interpretation": "Send it"})

    with pytest.raises(Exception):  # ActionUnavailable, surfaced by propose_action
        propose_from_text(
            session, text="email the client", workspace_id=env["workspace"].id,
            scope_key=_personal(env), user_id=env["admin"].id,
        )


def test_a_model_returning_junk_parameters_is_refused(session, env, stub_intent):
    """Model output is untrusted input. Pydantic decides."""
    stub_intent({"found": True, "action_type": "commitment.create",
                 "params": {"what": ""}, "interpretation": "?"})

    with pytest.raises(ActionRejected):
        propose_from_text(
            session, text="remind me", workspace_id=env["workspace"].id,
            scope_key=_personal(env), user_id=env["admin"].id,
        )


def test_declining_to_guess_is_a_normal_outcome(session, env, stub_intent):
    stub_intent({"found": False, "interpretation": "That doesn't match anything Sentinel can do"})

    with pytest.raises(IntentUnclear):
        propose_from_text(
            session, text="make the company profitable", workspace_id=env["workspace"].id,
            scope_key=_personal(env), user_id=env["admin"].id,
        )


def test_natural_language_cannot_escape_rbac(session, env, stub_intent):
    """ATTACK: a member asks in prose for something only an admin may do.
    The text path uses the same authorization as every other path."""
    stub_intent({"found": True, "action_type": "calendar.create_event", "params": CAL,
                 "interpretation": "Create a team event"})

    with pytest.raises(NotAuthorized, match="channel admin"):
        propose_from_text(
            session, text="put standup on the team calendar", workspace_id=env["workspace"].id,
            scope_key=f"channel:{env['team'].id}", user_id=env["member"].id,
        )


def test_natural_language_cannot_cross_into_another_persons_scope(session, env, stub_intent):
    stub_intent({"found": True, "action_type": "commitment.create",
                 "params": {"what": "In their name"}, "interpretation": "x"})

    with pytest.raises(NotAuthorized):
        propose_from_text(
            session, text="remind them", workspace_id=env["workspace"].id,
            scope_key=_personal(env, env["member"]), user_id=env["admin"].id,
        )


# --- 2. calendar attendees -------------------------------------------------


def test_attendees_escalate_the_action_to_high_risk(session, env):
    """An event for yourself is a private write. The same event with
    attendees sends each of them an invitation."""
    alone = _propose(session, env, "calendar.create_event", CAL)
    with_people = _propose(session, env, "calendar.create_event",
                           {**CAL, "attendee_emails": ["colleague@acme.test"]})

    assert alone.risk == ActionRisk.MEDIUM
    assert with_people.risk == ActionRisk.HIGH
    assert with_people.status == ActionStatus.AWAITING_APPROVAL


def test_every_invitee_is_named_in_the_preview(session, env):
    """Nobody is invited by a count."""
    action = _propose(session, env, "calendar.create_event",
                      {**CAL, "attendee_emails": ["a@acme.test", "b@acme.test"]})

    assert action.preview["fields"]["Invites"] == "a@acme.test, b@acme.test"
    assert "sends an invitation to 2 people" in action.preview["effect"]


def test_an_invalid_attendee_address_is_rejected(session, env):
    with pytest.raises(ActionRejected):
        _propose(session, env, "calendar.create_event", {**CAL, "attendee_emails": ["not-an-email"]})


def test_duplicate_attendees_are_collapsed(session, env):
    action = _propose(session, env, "calendar.create_event",
                      {**CAL, "attendee_emails": ["a@acme.test", "A@acme.test ", "a@acme.test"]})

    assert action.params["attendee_emails"] == ["a@acme.test"]


def test_an_event_with_attendees_can_never_run_unattended(session, env):
    """High risk, and the policy gate refuses it regardless of any opt-in."""
    allowed, why = autonomy_allows(
        session, scope_key=_personal(env), action_type="calendar.create_event", risk=ActionRisk.HIGH
    )
    assert allowed is False
    assert "never run unattended" in why or "low-risk" in why


# --- 3. bounded autonomy ---------------------------------------------------


def test_nothing_runs_unattended_by_default(session, env):
    """The default is off, and the refusal explains itself."""
    allowed, why = autonomy_allows(
        session, scope_key=_personal(env), action_type="commitment.create", risk=ActionRisk.LOW
    )

    assert allowed is False
    assert "Nobody has enabled" in why


def test_an_explicit_opt_in_allows_a_low_risk_reversible_action(session, env):
    set_policy(
        session, workspace_id=env["workspace"].id, scope_key=_personal(env),
        action_type="commitment.create", enabled=True, user_id=env["admin"].id,
    )

    allowed, why = autonomy_allows(
        session, scope_key=_personal(env), action_type="commitment.create", risk=ActionRisk.LOW
    )

    assert allowed is True
    assert "0/5 used today" in why


def test_an_action_the_registry_never_allows_cannot_be_opted_into(session, env):
    """ATTACK: enable autonomy for a calendar write. Refused at policy-set
    time so an impossible policy cannot be stored and later look like
    consent."""
    with pytest.raises(PolicyDenied, match="can never run unattended"):
        set_policy(
            session, workspace_id=env["workspace"].id, scope_key=_personal(env),
            action_type="calendar.create_event", enabled=True, user_id=env["admin"].id,
        )


def test_a_merely_compensatable_action_cannot_run_unattended(session, env):
    """Reversible is required, not compensatable: undoing a calendar invite
    still notifies everyone who received it."""
    spec = action_registry.REGISTRY["calendar.create_event"]
    assert spec.reversibility is Reversibility.COMPENSATABLE
    assert spec.autonomy_eligible is False


def test_a_channel_member_cannot_enable_autonomy_for_the_channel(session, env):
    """The unit of consent matches the unit of consequence."""
    with pytest.raises(PolicyDenied, match="channel admin"):
        set_policy(
            session, workspace_id=env["workspace"].id, scope_key=f"channel:{env['team'].id}",
            action_type="commitment.create", enabled=True, user_id=env["member"].id,
        )


def test_nobody_can_set_policy_in_another_persons_scope(session, env):
    with pytest.raises(PolicyDenied, match="your own context"):
        set_policy(
            session, workspace_id=env["workspace"].id, scope_key=_personal(env, env["member"]),
            action_type="commitment.create", enabled=True, user_id=env["admin"].id,
        )


def test_the_daily_limit_stops_a_runaway_loop(session, env):
    set_policy(
        session, workspace_id=env["workspace"].id, scope_key=_personal(env),
        action_type="commitment.create", enabled=True, daily_limit=2, user_id=env["admin"].id,
    )
    for n in range(2):
        action = _propose(session, env, "commitment.create", {"what": f"Thing {n}"})
        execute_action(session, action, env["admin"].id)

    allowed, why = autonomy_allows(
        session, scope_key=_personal(env), action_type="commitment.create", risk=ActionRisk.LOW
    )

    assert allowed is False
    assert "Daily limit reached (2/2)" in why


def test_disabling_leaves_the_record_of_who_turned_it_on(session, env):
    set_policy(session, workspace_id=env["workspace"].id, scope_key=_personal(env),
               action_type="commitment.create", enabled=True, user_id=env["admin"].id)
    set_policy(session, workspace_id=env["workspace"].id, scope_key=_personal(env),
               action_type="commitment.create", enabled=False, user_id=env["admin"].id)

    policy = session.execute(select(ActionPolicy)).scalars().one()
    assert policy.enabled is False
    assert policy.enabled_by_user_id == env["admin"].id  # the trail survives


# --- 4. compensation -------------------------------------------------------


def test_undoing_a_commitment_dismisses_it(session, env):
    action = _propose(session, env, "commitment.create", {"what": "Send the report"})
    execute_action(session, action, env["admin"].id)

    undo_action(session, action, env["admin"].id)

    commitment = session.get(Commitment, uuid.UUID(action.result["commitment_id"]))
    assert commitment.status == CommitmentStatus.DISMISSED
    assert action.undone_at is not None
    assert action.undone_by_user_id == env["admin"].id


def test_undoing_a_goal_abandons_it(session, env):
    action = _propose(session, env, "goal.create", {"title": "Launch V2"})
    execute_action(session, action, env["admin"].id)

    undo_action(session, action, env["admin"].id)

    goal = session.get(Goal, uuid.UUID(action.result["goal_id"]))
    assert goal.health == GoalHealth.ABANDONED


def test_the_record_keeps_that_it_happened_and_was_undone(session, env):
    """"Done and then taken back" is a different fact from "never happened",
    and an audit trail that loses the first is not an audit trail."""
    action = _propose(session, env, "commitment.create", {"what": "Send the report"})
    execute_action(session, action, env["admin"].id)
    undo_action(session, action, env["admin"].id)

    assert action.status == ActionStatus.SUCCEEDED  # it did happen
    assert action.executed_at is not None
    assert action.undone_at is not None
    assert action.undo_result


def test_undoing_twice_does_not_act_twice(session, env, monkeypatch):
    """For a compensatable action a second undo would mean a second provider
    call - and a second cancellation notice."""
    calls = {"n": 0}
    spec = action_registry.REGISTRY["commitment.create"]
    original = spec.compensate

    def _counting(session_, action_):
        calls["n"] += 1
        return original(session_, action_)

    monkeypatch.setattr(spec, "compensate", _counting)

    action = _propose(session, env, "commitment.create", {"what": "Send the report"})
    execute_action(session, action, env["admin"].id)
    undo_action(session, action, env["admin"].id)
    undo_action(session, action, env["admin"].id)

    assert calls["n"] == 1


def test_an_unexecuted_action_cannot_be_undone(session, env):
    action = _propose(session, env, "calendar.create_event", CAL)

    with pytest.raises(ActionRejected, match="Only an executed action"):
        undo_action(session, action, env["admin"].id)


def test_undo_is_authorized_like_every_other_action(session, env):
    action = _propose(session, env, "commitment.create", {"what": "Ship it"},
                      scope=f"channel:{env['team'].id}")
    execute_action(session, action, env["admin"].id)

    outsider = User(email="nobody@acme.test", name="Nobody")
    session.add(outsider)
    session.commit()

    with pytest.raises(NotAuthorized):
        undo_action(session, action, outsider.id)


def test_reversibility_is_declared_for_every_action(session, env):
    """The property that makes "can this be undone?" answerable without
    trying it."""
    for spec in action_registry.REGISTRY.values():
        assert spec.reversibility in Reversibility
        if spec.reversibility is Reversibility.IRREVERSIBLE:
            assert spec.compensate is None  # no button that cannot work
        elif spec.available:
            assert spec.compensate is not None


def test_the_calendar_undo_admits_invitations_cannot_be_unsent(session, env, monkeypatch):
    """Compensation, not rollback - and the wording says so."""
    spec = action_registry.REGISTRY["calendar.create_event"]

    monkeypatch.setattr(spec, "execute", lambda s, a: {
        "event_id": "evt-1", "title": "Standup", "url": "https://cal/x",
        "start": CAL["start"], "attendee_emails": ["a@acme.test"],
        "connection_id": str(uuid.uuid4()),
    })
    monkeypatch.setattr(spec, "verify", lambda s, a, r: (True, "Read back"))
    monkeypatch.setattr(spec, "compensate", lambda s, a: (
        "The event was deleted. Everyone invited has been notified of the cancellation - "
        "the invitation itself cannot be unsent."
    ))

    action = _propose(session, env, "calendar.create_event", {**CAL, "attendee_emails": ["a@acme.test"]})
    approve_action(session, action, env["admin"].id)
    execute_action(session, action, env["admin"].id)
    undo_action(session, action, env["admin"].id)

    assert "cannot be unsent" in action.undo_result
