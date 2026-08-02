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
from app.models.goal import Goal, GoalCommitment, GoalHealth, GoalRelation, GoalSituation
from app.models.situation import ProactiveSituation, ProactiveStatus
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


def relevant_situations(session: Session, goal: Goal) -> list[tuple[ProactiveSituation, GoalSituation]]:
    """Situations that have an *established* relationship to this goal.

    Scope alone is not a relationship. Before this, every active situation in
    a scope influenced every goal in it, so one noisy channel could mark
    unrelated goals at risk and "at risk" stopped carrying information.

    A relationship is established one of two ways:

      deterministically  the situation and one of the goal's linked
                         commitments were built from the same signals - the
                         strongest evidence available, because it is literal
                         overlap rather than similarity
      by a person        someone classified it

    Anything else is UNRELATED and contributes nothing. Keyword resemblance
    is deliberately not enough: "Launch V2" and "V2 newsletter bounced" share
    a token and nothing else.
    """
    links = {
        link.situation_id: link
        for link in session.execute(
            select(GoalSituation).where(GoalSituation.goal_id == goal.id)
        ).scalars()
    }
    if not links:
        return []

    situations = session.execute(
        select(ProactiveSituation).where(
            ProactiveSituation.id.in_(links.keys()),
            ProactiveSituation.scope_key == goal.scope_key,  # re-checked, never trusted
            ProactiveSituation.status.in_([ProactiveStatus.ACTIVE, ProactiveStatus.EMERGING]),
        )
    ).scalars().all()
    return [(s, links[s.id]) for s in situations]


def detect_situation_relations(session: Session, goal: Goal) -> int:
    """Establish relationships Sentinel can prove, and only those.

    Signal overlap is the test: if a situation was detected from a signal
    that also backs one of this goal's linked commitments, they are about the
    same underlying events. That is a fact, not a resemblance.

    Auto-detected relations are RISK - enough to surface, never enough to
    declare BLOCKING, which stays a human judgement. A person's existing
    classification is never overwritten.
    """
    commitment_signals: set[str] = set()
    for commitment in linked_commitments(session, goal):
        for entry in commitment.evidence or []:
            if entry.get("signal_id"):
                commitment_signals.add(entry["signal_id"])
    if not commitment_signals:
        return 0

    existing = {
        link.situation_id: link
        for link in session.execute(
            select(GoalSituation).where(GoalSituation.goal_id == goal.id)
        ).scalars()
    }

    candidates = session.execute(
        select(ProactiveSituation).where(
            ProactiveSituation.scope_key == goal.scope_key,
            ProactiveSituation.status.in_([ProactiveStatus.ACTIVE, ProactiveStatus.EMERGING]),
        )
    ).scalars().all()

    established = 0
    for situation in candidates:
        overlap = {e.get("signal_id") for e in (situation.evidence or [])} & commitment_signals
        if not overlap:
            continue
        link = existing.get(situation.id)
        if link is not None:
            if not link.auto_detected:
                continue  # a person decided; leave it alone
            link.reason = _overlap_reason(len(overlap))
            continue
        session.add(GoalSituation(
            goal_id=goal.id, situation_id=situation.id, relation=GoalRelation.RISK,
            auto_detected=True, reason=_overlap_reason(len(overlap)),
        ))
        established += 1

    if established:
        session.commit()
    return established


def set_situation_relation(
    session: Session, goal: Goal, situation: ProactiveSituation, relation: GoalRelation, user_id: uuid.UUID
) -> Goal:
    """A person classifying evidence. Scope is re-checked here too, so a
    private situation can never be attached to a channel goal."""
    if situation.scope_key != goal.scope_key:
        raise NotAuthorized("That situation belongs to a different context")

    link = session.execute(
        select(GoalSituation).where(
            GoalSituation.goal_id == goal.id, GoalSituation.situation_id == situation.id
        )
    ).scalar_one_or_none()
    if link is None:
        link = GoalSituation(goal_id=goal.id, situation_id=situation.id)
        session.add(link)
    link.relation = relation
    link.auto_detected = False
    link.reason = "Classified by a person"
    link.set_by_user_id = user_id
    session.commit()

    reassess_goal(session, goal)
    return goal


def _overlap_reason(count: int) -> str:
    return f"Shares {count} signal{'s' if count > 1 else ''} with a linked commitment"


def suggest_commitments(session: Session, goal: Goal, *, limit: int = 5) -> list[dict]:
    """Commitments that *might* belong to this goal, for a person to confirm.

    Never auto-linked. Suggestion is cheap and reversible; a wrong link
    silently changes a goal's health, so the two get very different bars.
    Ranked by shared meaningful words between the commitment and the goal's
    title and stated outcome - weak evidence, which is exactly why it
    produces a suggestion rather than a link.
    """
    from app.services.meeting_prep import meaningful_keywords

    linked = {c.id for c in linked_commitments(session, goal)}
    keywords = {k.lower() for k in meaningful_keywords(f"{goal.title} {goal.outcome or ''}")}
    if not keywords:
        return []

    candidates = session.execute(
        select(Commitment).where(
            Commitment.scope_key == goal.scope_key,  # never crosses scopes
            Commitment.status.in_(_OPEN_COMMITMENT),
        )
    ).scalars().all()

    scored = []
    for commitment in candidates:
        if commitment.id in linked:
            continue
        words = {w.lower() for w in meaningful_keywords(commitment.what)}
        shared = keywords & words
        if not shared:
            continue
        scored.append({
            "commitment_id": str(commitment.id),
            "what": commitment.what,
            "status": commitment.status.value,
            "due_at": _aware(commitment.due_at).isoformat() if commitment.due_at else None,
            "shared_terms": sorted(shared),
            "reason": f"Mentions {', '.join(sorted(shared)[:3])}",
        })

    scored.sort(key=lambda s: -len(s["shared_terms"]))
    return scored[:limit]


def _assess(session: Session, goal: Goal, now: datetime) -> Assessment:
    """Health, progress and reasons - all arithmetic, all explainable."""
    commitments = _weighted_commitments(session, goal)
    related = relevant_situations(session, goal)

    reasons: list[str] = []
    blockers: list[dict] = []
    risks: list[dict] = []

    resolved = [(c, w) for c, w in commitments if c.status == CommitmentStatus.RESOLVED]
    open_ones = [(c, w) for c, w in commitments if c.status in _OPEN_COMMITMENT]
    overdue = [c for c, _ in commitments if c.status == CommitmentStatus.OVERDUE]
    at_risk = [c for c, _ in commitments if c.status == CommitmentStatus.AT_RISK]

    # Progress by weight, so one large commitment is not worth the same as a
    # trivial one. Weight defaults to 1.0, which keeps the simple case a
    # plain count. Dismissed commitments are excluded from both sides rather
    # than counted as done - that would inflate progress for work abandoned.
    done_weight = sum(w for _, w in resolved)
    total_weight = done_weight + sum(w for _, w in open_ones)
    progress = round(done_weight / total_weight, 2) if total_weight else None

    if not commitments:
        reasons.append("Nothing linked yet, so progress cannot be determined.")
    elif any(w != 1.0 for _, w in commitments):
        reasons.append(f"{done_weight:g} of {total_weight:g} weighted work resolved.")
    else:
        reasons.append(f"{len(resolved)} of {len(resolved) + len(open_ones)} linked commitments resolved.")

    for commitment in overdue:
        blockers.append(_commitment_ref(commitment, "overdue"))
    if overdue:
        reasons.append(f"{len(overdue)} linked commitment{'s' if len(overdue) > 1 else ''} overdue.")

    for commitment in at_risk:
        risks.append(_commitment_ref(commitment, "at risk"))
    if at_risk:
        reasons.append(f"{len(at_risk)} linked commitment{'s' if len(at_risk) > 1 else ''} showing no progress.")

    # Only situations with an established relationship count, and the
    # relation decides how much. UNRELATED and RELATED are shown but move
    # nothing - a situation has to be classified RISK or BLOCKING to change
    # a goal's health.
    situation_blockers = [(s, l) for s, l in related if l.relation == GoalRelation.BLOCKING]
    situation_risks = [(s, l) for s, l in related if l.relation == GoalRelation.RISK]

    for situation, link in situation_blockers:
        blockers.append(_situation_ref(situation, link, "blocking"))
    for situation, link in situation_risks:
        risks.append(_situation_ref(situation, link, "risk"))

    if situation_blockers:
        reasons.append(f"{len(situation_blockers)} situation(s) blocking this goal.")
    if situation_risks:
        reasons.append(f"{len(situation_risks)} related situation(s) putting this at risk.")

    due = _aware(goal.due_at)
    deadline_passed = due is not None and due < now
    deadline_near = due is not None and not deadline_passed and (due - now) <= DEADLINE_HORIZON
    if deadline_passed and open_ones:
        reasons.append("The deadline has passed with work still open.")
    elif deadline_near and open_ones:
        hours = max(1, int((due - now).total_seconds() // 3600))
        reasons.append(f"Deadline in {hours}h with {len(open_ones)} commitment(s) still open.")

    if overdue or situation_blockers:
        health = GoalHealth.BLOCKED
    elif deadline_passed and open_ones:
        health = GoalHealth.BLOCKED
    elif at_risk or situation_risks or (deadline_near and open_ones):
        health = GoalHealth.AT_RISK
    elif commitments:
        health = GoalHealth.ON_TRACK
    else:
        health = GoalHealth.UNKNOWN

    return Assessment(health=health, progress=progress, reasons=reasons, blockers=blockers, risks=risks)


def _weighted_commitments(session: Session, goal: Goal) -> list[tuple[Commitment, float]]:
    rows = session.execute(
        select(Commitment, GoalCommitment.weight)
        .join(GoalCommitment, GoalCommitment.commitment_id == Commitment.id)
        .where(GoalCommitment.goal_id == goal.id)
    ).all()
    return [(commitment, float(weight or 1.0)) for commitment, weight in rows]


def set_commitment_weight(session: Session, goal: Goal, commitment_id: uuid.UUID, weight: float) -> Goal:
    """How much of the goal this commitment represents. Not a task hierarchy -
    just a way to say "the backend is most of this" without inventing
    sub-goals, milestones and dependency edges."""
    link = session.execute(
        select(GoalCommitment).where(
            GoalCommitment.goal_id == goal.id, GoalCommitment.commitment_id == commitment_id
        )
    ).scalar_one_or_none()
    if link is None:
        raise NotAuthorized("That commitment is not linked to this goal")
    link.weight = max(0.1, min(100.0, float(weight)))
    session.commit()
    reassess_goal(session, goal)
    return goal


def _situation_ref(situation: ProactiveSituation, link, detail: str) -> dict:
    return {
        "kind": "situation",
        "id": str(situation.id),
        "title": situation.title,
        "detail": f"{detail} · {link.reason}" if link.reason else detail,
    }


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


def reassess_goals_for_workspace(session: Session, workspace_id: uuid.UUID, *, scope_keys: set[str] | None = None) -> int:
    """Background entry point, narrowed to what could actually have changed.

    A full scan was fine at this size and will not be: every ingested GitHub
    or Slack event would otherwise re-evaluate every goal in the workspace,
    including goals whose evidence nothing touched. `scope_keys` limits the
    pass to the scopes whose commitments or situations were just refreshed,
    which is the set the caller already knows.

    Only *open* goals are considered, and each failure is contained - one bad
    goal must not stop the rest of a workspace being assessed.
    """
    query = select(Goal).where(Goal.workspace_id == workspace_id, Goal.health.notin_(_CLOSED))
    if scope_keys:
        query = query.where(Goal.scope_key.in_(scope_keys))

    goals = session.execute(query).scalars().all()
    for goal in goals:
        try:
            detect_situation_relations(session, goal)
            reassess_goal(session, goal)
        except Exception:
            session.rollback()
            logger.exception("goal_reassess_failed", goal_id=str(goal.id))

    logger.info(
        "goal_workspace_reassess",
        workspace_id=str(workspace_id), goals=len(goals), narrowed=bool(scope_keys),
    )
    return len(goals)


def reassess_goals_for_commitment(session: Session, commitment: Commitment) -> int:
    """Reassess exactly the goals that link this commitment.

    The incremental path for the future providers: a merged PR resolves one
    commitment, and only the goals that actually depend on it need looking
    at - not every goal in the workspace.
    """
    goals = session.execute(
        select(Goal)
        .join(GoalCommitment, GoalCommitment.goal_id == Goal.id)
        .where(GoalCommitment.commitment_id == commitment.id, Goal.health.notin_(_CLOSED))
    ).scalars().all()

    for goal in goals:
        try:
            reassess_goal(session, goal)
        except Exception:
            session.rollback()
            logger.exception("goal_reassess_failed", goal_id=str(goal.id))
    return len(goals)


def affected_scope_keys(session: Session, workspace_id: uuid.UUID) -> set[str]:
    """Scopes in this workspace that hold any goal - the widest set worth
    reassessing. Cheap, and keeps the caller from having to know how goals
    are keyed."""
    return set(session.execute(
        select(Goal.scope_key).where(Goal.workspace_id == workspace_id, Goal.health.notin_(_CLOSED))
    ).scalars())


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
                "weight": w,
            }
            for c, w in _weighted_commitments(session, goal)
        ],
        "blockers": assessment.blockers,
        "risks": assessment.risks,
        # Offered, never applied - a person confirms before anything moves.
        "suggested_commitments": suggest_commitments(session, goal),
    }
