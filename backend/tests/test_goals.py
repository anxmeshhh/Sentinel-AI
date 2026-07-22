"""Goal-Based AI: health as arithmetic, and the scope boundary.

The failure this module must avoid is confident nonsense - a launch declared
ON TRACK by something nobody can audit, or a "73% complete" nobody can trace.
So the tests are mostly about the computation: every health state is reachable
from stated reasons, progress is NULL rather than 0 when nothing is linked,
and no model is consulted to decide any of it.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.commitment import Commitment, CommitmentStatus
from app.models.connection import Connection, Provider
from app.models.goal import Goal, GoalCommitment, GoalHealth
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import SharedConnection, SharedScope
from app.models.situation import Situation, SituationKind, SituationStatus
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.commitments import create_manual_commitment, resolve_commitment
from app.services.goals import (
    NotAuthorized,
    close_goal,
    create_goal,
    goal_evidence,
    link_commitment,
    list_goals,
    reassess_goal,
    reassess_goals_for_workspace,
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

    admin_gmail = Connection(workspace_id=workspace.id, user_id=admin.id, provider=Provider.GMAIL,
                             org="admin@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW)
    session.add(admin_gmail)
    session.flush()
    session.add(SharedConnection(scope_type=SharedScope.WORKSPACE, scope_id=workspace.id,
                                 connection_id=admin_gmail.id, added_by_user_id=admin.id))
    session.commit()

    return {"workspace": workspace, "team": team, "admin": admin, "member": member}


def _personal(session, env, user=None):
    return personal_scope(session, env["workspace"].id, (user or env["admin"]).id)


def _goal(session, env, title="Launch Product V2", *, due_at=None, scope=None, user=None):
    return create_goal(
        session, workspace_id=env["workspace"].id, scope=scope or _personal(session, env),
        title=title, outcome="V2 live for all customers", due_at=due_at,
        user_id=(user or env["admin"]).id,
    )


def _commitment(session, env, what, *, due_at=None, scope=None, user=None):
    return create_manual_commitment(
        session, workspace_id=env["workspace"].id, scope=scope or _personal(session, env),
        what=what, due_at=due_at, user_id=(user or env["admin"]).id,
    )


def _link(session, env, goal, commitment):
    return link_commitment(session, goal, commitment, env["admin"].id)


# --- health is arithmetic --------------------------------------------------


def test_a_goal_with_nothing_linked_admits_it_cannot_judge(session, env):
    """The most important honesty case. A confident 0% would imply Sentinel
    looked and found nothing done."""
    goal = _goal(session, env)

    assert goal.health == GoalHealth.UNKNOWN
    assert goal.progress is None
    assert "cannot be determined" in " ".join(goal.health_reasons)


def test_linked_and_healthy_is_on_track(session, env):
    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    _link(session, env, goal, _commitment(session, env, "Finish the backend", due_at=NOW + timedelta(days=20)))

    session.refresh(goal)
    assert goal.health == GoalHealth.ON_TRACK
    assert goal.progress == 0.0  # measurable now: 0 of 1


def test_progress_is_a_ratio_of_real_commitments(session, env):
    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    done = _commitment(session, env, "Ship the API", due_at=NOW + timedelta(days=10))
    _link(session, env, goal, done)
    _link(session, env, goal, _commitment(session, env, "Ship the UI", due_at=NOW + timedelta(days=10)))
    resolve_commitment(session, done, reason="shipped")

    reassess_goal(session, goal)

    assert goal.progress == 0.5
    assert "1 of 2 linked commitments resolved" in " ".join(goal.health_reasons)


def test_an_overdue_commitment_blocks_the_goal(session, env):
    """The example from the brief: the launch is blocked because the backend
    commitment is overdue - and the reason says exactly that."""
    goal = _goal(session, env, due_at=NOW + timedelta(days=10))
    _link(session, env, goal, _commitment(session, env, "Finish the backend", due_at=NOW - timedelta(days=1)))

    session.refresh(goal)
    assert goal.health == GoalHealth.BLOCKED
    assert "overdue" in " ".join(goal.health_reasons)

    evidence = goal_evidence(session, goal)
    assert evidence["blockers"][0]["title"] == "Finish the backend"


def _situation(session, env, scope_key, title, *, signal_ids=None):
    situation = Situation(
        workspace_id=env["workspace"].id, scope_key=scope_key,
        situation_key=f"service_jeopardy:{uuid.uuid4().hex[:8]}", kind=SituationKind.SERVICE_JEOPARDY,
        status=SituationStatus.ACTIVE, title=title,
        evidence=[{"signal_id": sid} for sid in (signal_ids or [])],
        evidence_count=len(signal_ids or []), first_seen_at=NOW, last_evidence_at=NOW,
        importance=0.8, confidence=0.9,
    )
    session.add(situation)
    session.commit()
    return situation


def test_an_unrelated_situation_no_longer_creates_a_false_risk(session, env):
    """The regression this pass exists for. Sharing a scope is not a
    relationship - a busy channel would otherwise mark every goal at risk,
    and "at risk" would stop carrying information."""
    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    _link(session, env, goal, _commitment(session, env, "Finish the backend", due_at=NOW + timedelta(days=20)))
    _situation(session, env, _personal(session, env).key, "Unrelated vendor outage")

    reassess_goal(session, goal)

    assert goal.health == GoalHealth.ON_TRACK
    assert all("outage" not in r["title"] for r in goal_evidence(session, goal)["risks"])


def test_a_situation_sharing_a_signal_is_detected_as_a_risk(session, env):
    """The deterministic relationship: the situation was built from a signal
    that also backs one of this goal's commitments, so they are about the
    same events. That is literal overlap, not resemblance."""
    from app.services.goals import detect_situation_relations

    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    commitment = _commitment(session, env, "Fix the deploy", due_at=NOW + timedelta(days=20))
    shared_signal = str(uuid.uuid4())
    commitment.evidence = [{"signal_id": shared_signal, "kind": "email", "title": "deploy failed"}]
    session.commit()
    _link(session, env, goal, commitment)
    _situation(session, env, _personal(session, env).key, "Deployment instability", signal_ids=[shared_signal])

    established = detect_situation_relations(session, goal)
    reassess_goal(session, goal)

    assert established == 1
    assert goal.health == GoalHealth.AT_RISK
    assert any("Shares 1 signal" in r["detail"] for r in goal_evidence(session, goal)["risks"])


def test_a_person_can_mark_a_situation_blocking(session, env):
    from app.models.goal import GoalRelation
    from app.services.goals import set_situation_relation

    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    _link(session, env, goal, _commitment(session, env, "Finish the backend", due_at=NOW + timedelta(days=20)))
    situation = _situation(session, env, _personal(session, env).key, "Database is down")

    set_situation_relation(session, goal, situation, GoalRelation.BLOCKING, env["admin"].id)

    assert goal.health == GoalHealth.BLOCKED
    assert goal_evidence(session, goal)["blockers"][0]["title"] == "Database is down"


def test_marking_a_situation_unrelated_silences_it(session, env):
    from app.models.goal import GoalRelation
    from app.services.goals import set_situation_relation

    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    _link(session, env, goal, _commitment(session, env, "Finish the backend", due_at=NOW + timedelta(days=20)))
    situation = _situation(session, env, _personal(session, env).key, "Noisy thing")
    set_situation_relation(session, goal, situation, GoalRelation.RISK, env["admin"].id)
    assert goal.health == GoalHealth.AT_RISK

    set_situation_relation(session, goal, situation, GoalRelation.UNRELATED, env["admin"].id)

    assert goal.health == GoalHealth.ON_TRACK


def test_auto_detection_never_overwrites_a_persons_decision(session, env):
    """Someone said this doesn't matter. The next deterministic pass must not
    argue with them."""
    from app.models.goal import GoalRelation
    from app.services.goals import detect_situation_relations, set_situation_relation

    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    commitment = _commitment(session, env, "Fix the deploy", due_at=NOW + timedelta(days=20))
    shared_signal = str(uuid.uuid4())
    commitment.evidence = [{"signal_id": shared_signal}]
    session.commit()
    _link(session, env, goal, commitment)
    situation = _situation(session, env, _personal(session, env).key, "Deploy noise", signal_ids=[shared_signal])
    set_situation_relation(session, goal, situation, GoalRelation.UNRELATED, env["admin"].id)

    detect_situation_relations(session, goal)
    reassess_goal(session, goal)

    assert goal.health == GoalHealth.ON_TRACK


def test_a_passed_deadline_with_open_work_blocks(session, env):
    goal = _goal(session, env, due_at=NOW - timedelta(days=1))
    _link(session, env, goal, _commitment(session, env, "Finish the backend", due_at=NOW + timedelta(days=10)))

    session.refresh(goal)
    assert goal.health == GoalHealth.BLOCKED
    assert "deadline has passed" in " ".join(goal.health_reasons)


def test_a_near_deadline_with_open_work_is_a_risk(session, env):
    goal = _goal(session, env, due_at=NOW + timedelta(hours=10))
    _link(session, env, goal, _commitment(session, env, "Finish the backend", due_at=NOW + timedelta(days=10)))

    session.refresh(goal)
    assert goal.health == GoalHealth.AT_RISK


def test_every_health_state_carries_a_stated_reason(session, env):
    """No health without an explanation a person can check."""
    goal = _goal(session, env, due_at=NOW + timedelta(days=10))
    _link(session, env, goal, _commitment(session, env, "Overdue thing", due_at=NOW - timedelta(days=2)))

    session.refresh(goal)
    assert goal.health_reasons
    assert all(isinstance(r, str) and r for r in goal.health_reasons)


def test_health_is_identical_with_the_model_unreachable(session, env, monkeypatch):
    """The model explains health; it never decides it. So an unreachable
    model must cost the prose and nothing else - same state, same reasons,
    same progress."""
    import app.services.goals as module
    from app.agents.llm import LLMError

    class _Unreachable:
        def complete_json(self, **_kwargs):
            raise LLMError("quota exhausted")

    monkeypatch.setattr(module, "LLMClient", _Unreachable)

    goal = _goal(session, env, due_at=NOW + timedelta(days=10))
    _link(session, env, goal, _commitment(session, env, "Overdue thing", due_at=NOW - timedelta(days=2)))

    session.refresh(goal)
    assert goal.health == GoalHealth.BLOCKED
    assert goal.progress == 0.0
    assert "overdue" in " ".join(goal.health_reasons)
    assert goal.assessment is None  # only the prose is missing
    assert goal.llm_calls == 0


def test_the_model_is_told_the_health_is_already_decided(session, env, monkeypatch):
    """Guards the prompt itself: if it ever starts asking the model to judge
    the goal, this fails. That instruction is what keeps "73% complete" out."""
    import app.services.goals as module

    captured = {}

    class _Capture:
        def complete_json(self, *, system, user, **_kwargs):
            captured["system"] = system
            captured["user"] = user
            return {"assessment": "ok", "next_step": "do the thing"}

    monkeypatch.setattr(module, "LLMClient", _Capture)

    goal = _goal(session, env, due_at=NOW + timedelta(days=10))
    _link(session, env, goal, _commitment(session, env, "Overdue thing", due_at=NOW - timedelta(days=2)))

    assert "ALREADY been computed" in captured["system"]
    assert "do not dispute, recompute or" in captured["system"]
    assert "never state a percentage that is not the supplied progress" in captured["system"]
    # The computed state is supplied as fact, not asked for.
    assert "computed_health" in captured["user"]


# --- lifecycle -------------------------------------------------------------


def test_only_a_person_marks_a_goal_achieved(session, env):
    """Sentinel can say a goal looks blocked; it cannot know the outcome was
    reached, because "done" is defined by whoever set it."""
    goal = _goal(session, env)

    closed = close_goal(session, goal, achieved=True)

    assert closed.health == GoalHealth.ACHIEVED
    assert closed.closed_at is not None
    assert list_goals(session, _personal(session, env)) == []


def test_a_closed_goal_stops_being_reassessed(session, env):
    goal = _goal(session, env, due_at=NOW + timedelta(days=10))
    _link(session, env, goal, _commitment(session, env, "Overdue thing", due_at=NOW - timedelta(days=2)))
    close_goal(session, goal, achieved=True)

    reassess_goal(session, goal)

    assert goal.health == GoalHealth.ACHIEVED  # not dragged back to BLOCKED


def test_reassessment_is_idempotent_and_spends_nothing_when_stable(session, env):
    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    _link(session, env, goal, _commitment(session, env, "Finish the backend", due_at=NOW + timedelta(days=20)))
    session.refresh(goal)
    calls_before = goal.llm_calls

    reassess_goal(session, goal)
    reassess_goal(session, goal)

    assert goal.llm_calls == calls_before  # state unchanged, no re-explanation


def test_the_background_pass_reassesses_open_goals(session, env):
    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    commitment = _commitment(session, env, "Finish the backend", due_at=NOW + timedelta(days=20))
    _link(session, env, goal, commitment)
    session.refresh(goal)
    assert goal.health == GoalHealth.ON_TRACK

    # Time passes and the commitment goes overdue.
    commitment.due_at = NOW - timedelta(days=1)
    commitment.status = CommitmentStatus.OVERDUE
    session.commit()

    reassess_goals_for_workspace(session, env["workspace"].id)

    session.refresh(goal)
    assert goal.health == GoalHealth.BLOCKED


# --- the boundary ----------------------------------------------------------


def test_a_private_commitment_cannot_be_linked_to_a_channel_goal(session, env):
    """ATTACK: the whole security story of this module. If a private promise
    could move a team goal, its health - and its stated reasons, which name
    the commitment - would leak private work to the channel."""
    channel_goal = _goal(session, env, "Launch V2", scope=channel_scope(session, env["team"].id))
    private = _commitment(
        session, env, "Ask about my raise",
        scope=_personal(session, env, env["member"]), user=env["member"],
    )

    with pytest.raises(NotAuthorized):
        link_commitment(session, channel_goal, private, env["admin"].id)


def test_a_channel_commitment_cannot_be_linked_to_a_private_goal(session, env):
    private_goal = _goal(session, env, "My prep")
    shared = _commitment(
        session, env, "Ship the release", scope=channel_scope(session, env["team"].id),
    )

    with pytest.raises(NotAuthorized):
        link_commitment(session, private_goal, shared, env["admin"].id)


def test_private_and_channel_goals_do_not_appear_in_each_others_lists(session, env):
    _goal(session, env, "My private prep")
    _goal(session, env, "Launch V2", scope=channel_scope(session, env["team"].id))

    mine = [g.title for g in list_goals(session, _personal(session, env))]
    theirs = [g.title for g in list_goals(session, channel_scope(session, env["team"].id))]

    assert mine == ["My private prep"]
    assert theirs == ["Launch V2"]


def test_a_private_situation_never_affects_a_channel_goal(session, env):
    """Situations are matched on scope_key, so a private one is invisible to
    a channel goal even though both live in one workspace."""
    channel_goal = _goal(session, env, "Launch V2", scope=channel_scope(session, env["team"].id))
    _link(session, env, channel_goal, _commitment(
        session, env, "Ship it", due_at=NOW + timedelta(days=20), scope=channel_scope(session, env["team"].id)
    ))
    session.add(Situation(
        workspace_id=env["workspace"].id, scope_key=_personal(session, env, env["member"]).key,
        situation_key="service_jeopardy:private", kind=SituationKind.SERVICE_JEOPARDY,
        status=SituationStatus.ACTIVE, title="My private service is down",
        evidence=[], evidence_count=1, first_seen_at=NOW, last_evidence_at=NOW,
        importance=0.8, confidence=0.9,
    ))
    session.commit()

    reassess_goal(session, channel_goal)

    assert channel_goal.health == GoalHealth.ON_TRACK
    assert all("private" not in r["title"].lower() for r in goal_evidence(session, channel_goal)["risks"])


def test_unlinking_recomputes_the_health(session, env):
    goal = _goal(session, env, due_at=NOW + timedelta(days=10))
    blocker = _commitment(session, env, "Overdue thing", due_at=NOW - timedelta(days=2))
    _link(session, env, goal, blocker)
    session.refresh(goal)
    assert goal.health == GoalHealth.BLOCKED

    from app.services.goals import unlink_commitment

    unlink_commitment(session, goal, blocker.id)

    assert goal.health == GoalHealth.UNKNOWN
    assert goal.progress is None


def test_linking_the_same_commitment_twice_is_one_link(session, env):
    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    commitment = _commitment(session, env, "Finish the backend", due_at=NOW + timedelta(days=20))
    _link(session, env, goal, commitment)
    _link(session, env, goal, commitment)

    links = session.execute(select(GoalCommitment).where(GoalCommitment.goal_id == goal.id)).scalars().all()
    assert len(links) == 1
    assert goal.progress == 0.0  # not 0 of 2


# --- weighted progress -----------------------------------------------------


def test_weights_let_one_commitment_carry_more_of_the_goal(session, env):
    """Five linked items where one is the real work should not read 20% when
    that one lands."""
    from app.services.goals import set_commitment_weight

    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    backend = _commitment(session, env, "Build the backend", due_at=NOW + timedelta(days=20))
    changelog = _commitment(session, env, "Update the changelog", due_at=NOW + timedelta(days=20))
    _link(session, env, goal, backend)
    _link(session, env, goal, changelog)
    set_commitment_weight(session, goal, backend.id, 9.0)

    resolve_commitment(session, backend, reason="done")
    reassess_goal(session, goal)

    assert goal.progress == 0.9  # not 0.5
    assert "weighted work resolved" in " ".join(goal.health_reasons)


def test_unweighted_goals_still_read_as_a_plain_count(session, env):
    """The simple case must not start speaking in weights."""
    goal = _goal(session, env, due_at=NOW + timedelta(days=30))
    done = _commitment(session, env, "Ship the API", due_at=NOW + timedelta(days=10))
    _link(session, env, goal, done)
    _link(session, env, goal, _commitment(session, env, "Ship the UI", due_at=NOW + timedelta(days=10)))
    resolve_commitment(session, done, reason="shipped")

    reassess_goal(session, goal)

    assert goal.progress == 0.5
    assert "1 of 2 linked commitments resolved" in " ".join(goal.health_reasons)


def test_a_weight_cannot_be_set_on_an_unlinked_commitment(session, env):
    from app.services.goals import set_commitment_weight

    goal = _goal(session, env)
    stray = _commitment(session, env, "Unrelated")

    with pytest.raises(NotAuthorized):
        set_commitment_weight(session, goal, stray.id, 5.0)


# --- link suggestions ------------------------------------------------------


def test_suggestions_are_offered_never_applied(session, env):
    """Suggestion is cheap and reversible; a wrong link silently changes
    health. The two get very different bars."""
    from app.services.goals import suggest_commitments

    goal = _goal(session, env, "Launch Product V2", due_at=NOW + timedelta(days=30))
    _commitment(session, env, "Finish Product V2 backend", due_at=NOW + timedelta(days=10))

    suggestions = suggest_commitments(session, goal)

    assert len(suggestions) == 1
    # The shared terms are normalised to lowercase for matching.
    assert {"product", "v2"} & set(suggestions[0]["shared_terms"])
    assert suggestions[0]["reason"].startswith("Mentions ")
    # Offered only - health is untouched.
    session.refresh(goal)
    assert goal.health == GoalHealth.UNKNOWN
    assert goal.progress is None


def test_suggestions_never_cross_a_scope(session, env):
    """ATTACK: a private commitment must not even be *suggested* for a
    channel goal - the suggestion itself would disclose its wording."""
    from app.services.goals import suggest_commitments

    channel_goal = _goal(session, env, "Launch Product V2", scope=channel_scope(session, env["team"].id))
    _commitment(
        session, env, "Finish Product V2 secret prototype",
        scope=_personal(session, env, env["member"]), user=env["member"],
    )

    assert suggest_commitments(session, channel_goal) == []


def test_an_already_linked_commitment_is_not_suggested_again(session, env):
    from app.services.goals import suggest_commitments

    goal = _goal(session, env, "Launch Product V2", due_at=NOW + timedelta(days=30))
    commitment = _commitment(session, env, "Finish Product V2 backend", due_at=NOW + timedelta(days=10))
    _link(session, env, goal, commitment)

    assert suggest_commitments(session, goal) == []


def test_nothing_in_common_yields_no_suggestion(session, env):
    from app.services.goals import suggest_commitments

    goal = _goal(session, env, "Launch Product V2", due_at=NOW + timedelta(days=30))
    _commitment(session, env, "Book the dentist", due_at=NOW + timedelta(days=10))

    assert suggest_commitments(session, goal) == []


# --- incremental reassessment ----------------------------------------------


def test_reassessment_can_be_narrowed_to_affected_scopes(session, env):
    """Prepared for volume: a full scan is fine now and will not be once
    GitHub/Slack/Jira are feeding events in."""
    mine = _goal(session, env, "Private goal", due_at=NOW + timedelta(days=30))
    theirs = _goal(session, env, "Channel goal", scope=channel_scope(session, env["team"].id),
                   due_at=NOW + timedelta(days=30))
    _link(session, env, mine, _commitment(session, env, "Do the thing", due_at=NOW + timedelta(days=10)))

    touched = reassess_goals_for_workspace(
        session, env["workspace"].id, scope_keys={_personal(session, env).key}
    )

    assert touched == 1  # only the private scope was walked
    assert theirs.health == GoalHealth.UNKNOWN  # untouched, as expected


def test_a_commitment_change_reassesses_only_its_own_goals(session, env):
    from app.services.goals import reassess_goals_for_commitment

    linked_goal = _goal(session, env, "Linked goal", due_at=NOW + timedelta(days=30))
    other_goal = _goal(session, env, "Other goal", due_at=NOW + timedelta(days=30))
    commitment = _commitment(session, env, "Do the thing", due_at=NOW + timedelta(days=10))
    _link(session, env, linked_goal, commitment)
    _link(session, env, other_goal, _commitment(session, env, "Something else", due_at=NOW + timedelta(days=10)))

    touched = reassess_goals_for_commitment(session, commitment)

    assert touched == 1


def test_affected_scope_keys_lists_only_scopes_with_open_goals(session, env):
    from app.services.goals import affected_scope_keys

    goal = _goal(session, env, "Private goal")
    _goal(session, env, "Channel goal", scope=channel_scope(session, env["team"].id))
    close_goal(session, goal, achieved=True)

    keys = affected_scope_keys(session, env["workspace"].id)

    assert keys == {f"channel:{env['team'].id}"}


def test_a_private_situation_cannot_be_classified_onto_a_channel_goal(session, env):
    """The relevance layer must not become a way around the scope boundary."""
    from app.models.goal import GoalRelation
    from app.services.goals import set_situation_relation

    channel_goal = _goal(session, env, "Launch V2", scope=channel_scope(session, env["team"].id))
    private_situation = _situation(
        session, env, _personal(session, env, env["member"]).key, "My private outage"
    )

    with pytest.raises(NotAuthorized):
        set_situation_relation(
            session, channel_goal, private_situation, GoalRelation.BLOCKING, env["admin"].id
        )
