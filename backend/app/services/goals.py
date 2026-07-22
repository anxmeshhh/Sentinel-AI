"""Goal-Based AI: is the outcome we want actually going to happen?

An intelligence layer *above* the existing modules rather than beside them.
It detects nothing and stores no signals of its own - it points what Sentinel
already knows at one stated outcome:

    Commitment Intelligence -> what was promised, and whether it is slipping
    Proactive Intelligence  -> what is developing in this context
    the deadline            -> how much time is left

## Health is arithmetic, not opinion

`_assess` computes health, progress and the reasons from linked commitments
and the deadline. Every rule is a count or a date comparison, and each one
writes a plain-language reason a person can check. The model is asked only to
*explain* the computed state, and is explicitly told the state is already
decided.

That split exists because the failure mode here is uniquely damaging: a
confident "73% complete" that nobody can trace is worse than no number, and a
launch declared ON TRACK by a model that skimmed some text is worse still.

**Progress is NULL when nothing is linked**, and the UI says so. A goal with
no linked commitments has no measurable progress; showing 0% would imply
Sentinel had looked and found nothing done.

## Links are explicit, risks are contextual

Commitments are linked by a person. Situations are not linked at all - the
active ones in the same scope are reported as "risks in this context", which
is exactly what they are. Claiming a situation *caused* a goal to slip would
be an inference nothing in the data supports.

## Cost

Assessment is deterministic and runs on every ingestion cycle. The model is
called only when the computed state actually changes, which for a stable goal
is never. A quiet system costs nothing.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.llm import LLMClient, LLMError
from app.models.commitment import Commitment, CommitmentStatus
from app.models.goal import Goal, GoalCommitment, GoalHealth
from app.models.situation import Situation, SituationStatus
from app.services.investigation import Scope

logger = structlog.get_logger("sentinel.goals")

# A deadline inside this window turns unfinished work into a risk rather than
# a plan. Matches the commitment horizon so the two modules agree about what
# "soon" means.
DEADLINE_HORIZON = timedelta(hours=72)

_CLOSED = (GoalHealth.ACHIEVED, GoalHealth.ABANDONED)
_OPEN_COMMITMENT = (
    CommitmentStatus.PENDING,
    CommitmentStatus.DUE_SOON,
    CommitmentStatus.AT_RISK,
    CommitmentStatus.OVERDUE,
)


class GoalError(Exception):
    pass


class NotAuthorized(GoalError):
    pass


@dataclass
class Assessment:
    health: GoalHealth
    progress: float | None
    reasons: list[str] = field(default_factory=list)
    blockers: list[dict] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)

    def fingerprint(self) -> str:
        raw = f"{self.health.value}|{self.progress}|{'|'.join(sorted(self.reasons))}"
        return hashlib.sha256(raw.encode()).hexdigest()[:64]


# --- reading and writing goals --------------------------------------------


def list_goals(session: Session, scope: Scope, *, include_closed: bool = False) -> list[Goal]:
    query = select(Goal).where(Goal.scope_key == scope.key)
    if not include_closed:
        query = query.where(Goal.health.notin_(_CLOSED))
    rows = list(session.execute(query).scalars())

    order = {GoalHealth.BLOCKED: 0, GoalHealth.AT_RISK: 1, GoalHealth.ON_TRACK: 2, GoalHealth.UNKNOWN: 3}
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(rows, key=lambda g: (order.get(g.health, 9), _aware(g.due_at) or far_future))


def create_goal(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    scope: Scope,
    title: str,
    user_id: uuid.UUID,
    outcome: str | None = None,
    due_at: datetime | None = None,
) -> Goal:
    goal = Goal(
        workspace_id=workspace_id,
        scope_key=scope.key,
        title=title.strip(),
        outcome=(outcome or "").strip() or None,
        due_at=_aware(due_at),
        created_by_user_id=user_id,
        health=GoalHealth.UNKNOWN,
        health_reasons=["Nothing linked yet, so progress cannot be determined."],
    )
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


def link_commitment(session: Session, goal: Goal, commitment: Commitment, user_id: uuid.UUID) -> Goal:
    """Attach a commitment to a goal, within one scope.

    The scope check is the whole security story of this module: a channel
    goal may only be built from that channel's commitments, so a member's
    private promise can never move a team goal's health - or be visible in
    its reasons.
    """
    if commitment.scope_key != goal.scope_key:
        raise NotAuthorized("That commitment belongs to a different context")

    existing = session.execute(
        select(GoalCommitment).where(
            GoalCommitment.goal_id == goal.id, GoalCommitment.commitment_id == commitment.id
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(GoalCommitment(goal_id=goal.id, commitment_id=commitment.id, linked_by_user_id=user_id))
        session.commit()

    reassess_goal(session, goal)
    return goal


def unlink_commitment(session: Session, goal: Goal, commitment_id: uuid.UUID) -> Goal:
    link = session.execute(
        select(GoalCommitment).where(
            GoalCommitment.goal_id == goal.id, GoalCommitment.commitment_id == commitment_id
        )
    ).scalar_one_or_none()
    if link is not None:
        session.delete(link)
        session.commit()
    reassess_goal(session, goal)
    return goal


def close_goal(session: Session, goal: Goal, *, achieved: bool) -> Goal:
    """Achieved or abandoned - a person's call, never Sentinel's.

    Sentinel can say a goal looks blocked; it cannot know that the outcome
    was reached, because "done" is defined by the person who set it.
    """
    goal.health = GoalHealth.ACHIEVED if achieved else GoalHealth.ABANDONED
    goal.closed_at = datetime.now(timezone.utc)
    goal.health_reasons = ["Marked achieved by a person." if achieved else "Abandoned by a person."]
    session.commit()
    session.refresh(goal)
    return goal


def reopen_goal(session: Session, goal: Goal) -> Goal:
    goal.closed_at = None
    reassess_goal(session, goal)
    return goal


# --- assessment ------------------------------------------------------------


def linked_commitments(session: Session, goal: Goal) -> list[Commitment]:
    return list(session.execute(
        select(Commitment)
        .join(GoalCommitment, GoalCommitment.commitment_id == Commitment.id)
        .where(GoalCommitment.goal_id == goal.id)
    ).scalars())


def contextual_situations(session: Session, goal: Goal) -> list[Situation]:
    """Active situations in the goal's own scope.

    Reported as risks *in this context* rather than as causes. A deployment
    problem in a channel is genuinely relevant to that channel's launch goal,
    and claiming it is the reason for a delay would be an inference the data
    does not support.
    """
    return list(session.execute(
        select(Situation).where(
            Situation.scope_key == goal.scope_key,
            Situation.status.in_([SituationStatus.ACTIVE, SituationStatus.EMERGING]),
        )
    ).scalars())


def _assess(session: Session, goal: Goal, now: datetime) -> Assessment:
    """Health, progress and reasons - all arithmetic, all explainable."""
    commitments = linked_commitments(session, goal)
    situations = contextual_situations(session, goal)

    reasons: list[str] = []
    blockers: list[dict] = []
    risks: list[dict] = []

    resolved = [c for c in commitments if c.status == CommitmentStatus.RESOLVED]
    open_ones = [c for c in commitments if c.status in _OPEN_COMMITMENT]
    overdue = [c for c in commitments if c.status == CommitmentStatus.OVERDUE]
    at_risk = [c for c in commitments if c.status == CommitmentStatus.AT_RISK]

    # Progress: measurable only when something is linked. Counting dismissed
    # commitments would inflate it, so the denominator is resolved + open.
    measurable = len(resolved) + len(open_ones)
    progress = round(len(resolved) / measurable, 2) if measurable else None

    if not commitments:
        reasons.append("Nothing linked yet, so progress cannot be determined.")
    else:
        reasons.append(f"{len(resolved)} of {measurable} linked commitments resolved.")

    for commitment in overdue:
        blockers.append(_commitment_ref(commitment, "overdue"))
    if overdue:
        reasons.append(f"{len(overdue)} linked commitment{'s' if len(overdue) > 1 else ''} overdue.")

    for commitment in at_risk:
        risks.append(_commitment_ref(commitment, "at risk"))
    if at_risk:
        reasons.append(f"{len(at_risk)} linked commitment{'s' if len(at_risk) > 1 else ''} showing no progress.")

    for situation in situations:
        risks.append({
            "kind": "situation",
            "id": str(situation.id),
            "title": situation.title,
            "detail": f"{situation.status.value} situation in this context",
        })
    if situations:
        reasons.append(
            f"{len(situations)} active situation{'s' if len(situations) > 1 else ''} in this context."
        )

    due = _aware(goal.due_at)
    deadline_passed = due is not None and due < now
    deadline_near = due is not None and not deadline_passed and (due - now) <= DEADLINE_HORIZON
    if deadline_passed and open_ones:
        reasons.append("The deadline has passed with work still open.")
    elif deadline_near and open_ones:
        hours = max(1, int((due - now).total_seconds() // 3600))
        reasons.append(f"Deadline in {hours}h with {len(open_ones)} commitment(s) still open.")

    # The decision, in priority order. Every branch is reachable from the
    # reasons above, so the health can always be justified.
    if overdue:
        health = GoalHealth.BLOCKED
    elif deadline_passed and open_ones:
        health = GoalHealth.BLOCKED
    elif at_risk or situations or (deadline_near and open_ones):
        health = GoalHealth.AT_RISK
    elif commitments:
        health = GoalHealth.ON_TRACK
    else:
        health = GoalHealth.UNKNOWN

    return Assessment(health=health, progress=progress, reasons=reasons, blockers=blockers, risks=risks)


def reassess_goal(session: Session, goal: Goal, *, explain: bool = True) -> Goal:
    """Recompute health; explain only if the computed state actually moved."""
    if goal.health in _CLOSED:
        return goal

    assessment = _assess(session, goal, datetime.now(timezone.utc))
    goal.health = assessment.health
    goal.progress = assessment.progress
    goal.health_reasons = assessment.reasons

    fingerprint = assessment.fingerprint()
    if explain and fingerprint != goal.state_fingerprint:
        _explain(goal, assessment)
        goal.state_fingerprint = fingerprint

    session.commit()
    session.refresh(goal)
    return goal


def reassess_goals_for_workspace(session: Session, workspace_id: uuid.UUID) -> int:
    """Background entry point. Goals are stored per scope already, so this
    walks the goals themselves rather than re-deriving scopes - the linked
    commitments carry the authorization that matters, and they were checked
    when the link was made."""
    goals = session.execute(
        select(Goal).where(Goal.workspace_id == workspace_id, Goal.health.notin_(_CLOSED))
    ).scalars().all()

    for goal in goals:
        try:
            reassess_goal(session, goal)
        except Exception:
            session.rollback()
            logger.exception("goal_reassess_failed", goal_id=str(goal.id))

    logger.info("goal_workspace_reassess", workspace_id=str(workspace_id), goals=len(goals))
    return len(goals)


def _explain(goal: Goal, assessment: Assessment) -> None:
    """One LLM call, and only to put the computed state into words.

    The prompt states the health as a given. Asking a model to *decide* it
    would reintroduce exactly the unaccountable judgement this module is
    built to avoid.
    """
    facts = {
        "goal": goal.title,
        "desired_outcome": goal.outcome,
        "deadline": goal.due_at.isoformat() if goal.due_at else None,
        "computed_health": assessment.health.value,
        "computed_progress": assessment.progress,
        "why": assessment.reasons,
        "blockers": [b["title"] for b in assessment.blockers],
        "risks": [r["title"] for r in assessment.risks],
    }
    try:
        result = LLMClient().complete_json(
            system=(
                "You are Sentinel, reporting on a goal. The health and progress have ALREADY been "
                "computed from evidence and are given to you - do not dispute, recompute or "
                "second-guess them, and never state a percentage that is not the supplied progress. "
                "STRICT RULES: reason only from the supplied facts; never invent blockers, work "
                "items, dates or people. If nothing is linked, say plainly that there is not yet "
                "enough linked evidence to judge progress. Plain text, no markdown. "
                "assessment: 2-3 sentences on where this goal stands and why. "
                "next_step: ONE concrete, practical next action. "
                'Return JSON: {"assessment": "...", "next_step": "..."}'
            ),
            user=f"Goal data: {facts}",
        )
        goal.assessment = (result.get("assessment") or "").strip() or None
        goal.next_step = (result.get("next_step") or "").strip() or None
        goal.llm_calls += 1
    except LLMError:
        # The computed health and its reasons are already correct and already
        # shown; only the prose is missing.
        logger.info("goal_explanation_unavailable", goal_id=str(goal.id))
        goal.assessment = None
        goal.next_step = None


def _commitment_ref(commitment: Commitment, detail: str) -> dict:
    return {
        "kind": "commitment",
        "id": str(commitment.id),
        "title": commitment.what,
        "detail": detail if not commitment.owner_label else f"{detail} · {commitment.owner_label}",
    }


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def goal_evidence(session: Session, goal: Goal) -> dict:
    """Everything behind the health, for the UI and for investigation."""
    assessment = _assess(session, goal, datetime.now(timezone.utc))
    return {
        "commitments": [
            {
                "id": str(c.id), "what": c.what, "status": c.status.value,
                "owner_label": c.owner_label,
                "due_at": _aware(c.due_at).isoformat() if c.due_at else None,
            }
            for c in linked_commitments(session, goal)
        ],
        "blockers": assessment.blockers,
        "risks": assessment.risks,
    }
