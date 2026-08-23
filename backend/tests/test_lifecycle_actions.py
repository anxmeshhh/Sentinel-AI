"""Goal, memory and decision lifecycle changes are auditable actions.

Each of these was a direct write on its own route: no audit row, no
verification, no undo, and no single place recording that a *person* closed a
goal or forgot a pattern rather than Sentinel deciding to. They are LOW and
internal, so they still execute in one gesture - what is new is the record.

The engines themselves are untouched: these actions delegate to close_goal,
reopen_goal, forget_memory and set_decision_status. Health calculation,
recurrence and decay are not reimplemented here.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.action import Action, ActionStatus
from app.models.base import Base
from app.models.correlated_situation import Situation, SituationStatus
from app.models.decision import Decision, DecisionKind, DecisionStatus
from app.models.goal import Goal, GoalHealth
from app.models.memory import Memory, MemoryKind, MemoryStatus
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.action_registry import ActionRejected
from app.services.actions import execute_action, propose_action, undo_action

NOW = datetime.now(timezone.utc)


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
    ws = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()
    user = User(email="owner@acme.test", name="Owner")
    stranger = User(email="other@acme.test", name="Other")
    session.add_all([user, stranger])
    session.flush()
    session.add_all([
        Membership(workspace_id=ws.id, user_id=user.id, role=Role.EMPLOYEE),
        Membership(workspace_id=ws.id, user_id=stranger.id, role=Role.ORG_ADMIN),
    ])
    scope_key = f"personal:{user.id}"

    goal = Goal(workspace_id=ws.id, scope_key=scope_key, title="Ship V2", health=GoalHealth.ON_TRACK)
    memory = Memory(
        workspace_id=ws.id, scope_key=scope_key, kind=MemoryKind.RECURRING_SITUATION,
        subject_key="sit:1", summary="“Deploys keep failing” keeps recurring", strength=0.6,
        observation_count=2, status=MemoryStatus.ACTIVE, evidence={},
        first_observed_at=NOW, last_observed_at=NOW,
    )
    session.add_all([goal, memory])
    session.flush()

    # A real Situation: Decision.situation_id is a foreign key, and grounding
    # a proposal in a situation that does not exist is exactly what the
    # constraint is there to prevent.
    situation = Situation(
        workspace_id=ws.id, scope_key=scope_key, dedupe_key=f"sit-{uuid.uuid4().hex[:8]}",
        status=SituationStatus.OPEN, severity="review", title="Deploys keep failing",
        member_count=2, peak_member_count=2, provider_count=1, cross_provider=False,
        first_seen_at=NOW, last_activity_at=NOW,
    )
    session.add(situation)
    session.flush()

    decision = Decision(
        workspace_id=ws.id, scope_key=scope_key, situation_id=situation.id,
        kind=DecisionKind.RECOMMEND, action_key="attention.snooze", action="Snooze the noisy alert",
        grounded_in="memory", rationale="Seen 3 times", requires_confirmation=True,
        memory_informed=True, priority_score=0.8, status=DecisionStatus.PROPOSED,
    )
    session.add(decision)
    session.commit()
    return {
        "ws": ws, "user": user, "stranger": stranger, "scope_key": scope_key,
        "goal": goal, "memory": memory, "decision": decision, "_s": session,
    }


def _run(env, action_type, params, user=None):
    actor = user or env["user"]
    action = propose_action(
        env["_s"], workspace_id=env["ws"].id, scope_key=env["scope_key"],
        action_type=action_type, params=params, user_id=actor.id,
    )
    return execute_action(env["_s"], action, actor.id)


# --- goals ----------------------------------------------------------------


@pytest.mark.parametrize(
    "action_type,expected",
    [("goal.achieve", GoalHealth.ACHIEVED), ("goal.abandon", GoalHealth.ABANDONED)],
)
def test_closing_a_goal_is_audited_and_verified(session, env, action_type, expected):
    action = _run(env, action_type, {"goal_id": str(env["goal"].id)})

    assert action.status is ActionStatus.SUCCEEDED
    assert action.verification == f"Read back as {expected.value}"
    session.refresh(env["goal"])
    assert env["goal"].health is expected
    assert env["goal"].closed_at is not None
    # The engine's own reason survives - this action delegates, it does not
    # reimplement what a closed goal looks like.
    assert env["goal"].health_reasons


def test_undoing_a_close_reopens_the_goal(session, env):
    action = _run(env, "goal.achieve", {"goal_id": str(env["goal"].id)})
    undo_action(session, action, env["user"].id)

    session.refresh(env["goal"])
    # Reopened - which is what undo guarantees. Whether health is re-derived
    # afterwards is the Goal engine's decision (reopen_goal -> reassess_goal),
    # deliberately not re-specified here.
    assert env["goal"].closed_at is None


def test_reopening_is_itself_an_action(session, env):
    _run(env, "goal.abandon", {"goal_id": str(env["goal"].id)})
    action = _run(env, "goal.reopen", {"goal_id": str(env["goal"].id)})

    assert action.status is ActionStatus.SUCCEEDED
    session.refresh(env["goal"])
    assert env["goal"].closed_at is None


# --- memory ---------------------------------------------------------------


def test_forgetting_is_audited_verified_and_undoable(session, env):
    action = _run(env, "memory.forget", {"memory_id": str(env["memory"].id)})

    assert action.status is ActionStatus.SUCCEEDED
    assert action.verification == "Read back as forgotten"
    session.refresh(env["memory"])
    assert env["memory"].status is MemoryStatus.FORGOTTEN

    undo_action(session, action, env["user"].id)
    session.refresh(env["memory"])
    assert env["memory"].status is MemoryStatus.ACTIVE
    # Soft state throughout - the row was never deleted, so undo is a real
    # undo rather than a re-learn.
    assert env["memory"].forgotten_at is None


# --- decisions ------------------------------------------------------------


@pytest.mark.parametrize(
    "action_type,expected",
    [("decision.confirm", DecisionStatus.CONFIRMED), ("decision.dismiss", DecisionStatus.DISMISSED)],
)
def test_a_decision_transition_is_audited_and_reversible(session, env, action_type, expected):
    action = _run(env, action_type, {"decision_id": str(env["decision"].id)})

    assert action.status is ActionStatus.SUCCEEDED
    session.refresh(env["decision"])
    assert env["decision"].status is expected

    undo_action(session, action, env["user"].id)
    session.refresh(env["decision"])
    assert env["decision"].status is DecisionStatus.PROPOSED


def test_confirming_records_intent_and_executes_nothing(session, env):
    """Confirm-first is unchanged: agreeing with a proposal is not the same
    as running the work it proposes."""
    _run(env, "decision.confirm", {"decision_id": str(env["decision"].id)})

    # The only Action row is the confirmation itself - the decision's own
    # action_key was NOT proposed or run as a side effect.
    types = {a.action_type for a in session.query(Action).all()}
    assert types == {"decision.confirm"}


# --- scope ----------------------------------------------------------------


def test_a_record_from_another_scope_is_refused(session, env):
    """The executor asserts the record's own scope_key matches the action's,
    so reaching propose/execute directly cannot cross a boundary the route
    would have blocked."""
    action = propose_action(
        session, workspace_id=env["ws"].id,
        scope_key=f"personal:{env['stranger'].id}",  # the stranger's context
        action_type="goal.achieve", params={"goal_id": str(env["goal"].id)},
        user_id=env["stranger"].id,
    )
    result = execute_action(session, action, env["stranger"].id)

    assert result.status is ActionStatus.FAILED
    assert "does not belong to this context" in (result.error or "")
    session.refresh(env["goal"])
    assert env["goal"].health is GoalHealth.ON_TRACK  # untouched


def test_memory_and_decisions_are_personal_only(session, env):
    """Matching their routes. A channel's memory is shared state and who may
    retire it is a separate question from who may read it."""
    for action_type, params in (
        ("memory.forget", {"memory_id": str(env["memory"].id)}),
        ("decision.dismiss", {"decision_id": str(env["decision"].id)}),
    ):
        with pytest.raises(ActionRejected):
            propose_action(
                session, workspace_id=env["ws"].id, scope_key=f"channel:{uuid.uuid4()}",
                action_type=action_type, params=params, user_id=env["user"].id,
            )
