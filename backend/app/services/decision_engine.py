"""The Decision Engine - Intelligence Core, Phase 7 (final).

Turns each situation's deterministic Reasoning (priority + grounded recommended
actions) into safety-classified Decisions, boosted transparently by Memory. No
LLM is the source of truth here - the actions come from the reasoning, which
grounded them in real finding kinds; Memory's influence is recorded on the row
and in the rationale, so a raised priority is never opaque.

CONFIRM-FIRST IS ABSOLUTE. This engine only ever writes PROPOSED decisions.
Anything that would act on the world is DecisionKind.RECOMMEND with
requires_confirmation=True and stays proposed until a human confirms it through
the existing action path. It sends, closes, posts and deletes nothing.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.scope import Scope
from app.models.decision import Decision, DecisionKind, DecisionStatus
from app.models.situation_reasoning import SituationReasoning
from app.services.memory_engine import matching_memory
from app.services.situation_engine import list_situations

# Boost applied to a situation's priority when Memory says it recurs - a pattern
# that keeps happening deserves attention over a one-off of equal severity.
_MEMORY_BOOST = 25.0

# Which grounded finding kinds imply acting on the world (RECOMMEND, needs
# confirmation) versus a read/attention nudge (INFORM, no side effect). Default
# is the safe one: anything unknown requires confirmation.
_INFORM_KINDS = {
    "stale_pr", "resource_stalled", "important_email", "upcoming_meeting",
    "meeting_unprepared", "finding", "deadline", "service_jeopardy",
}
_RECOMMEND_KINDS = {"slack_blocker", "slack_urgent", "slack_mention"}


# How serious this is, said the way a person would say it rather than as a
# severity token echoed back at them.
_SEVERITY_PHRASE = {
    "critical": "This needs attention now",
    "review": "This is worth reviewing",
    "reminder": "A reminder",
}


def _classify(action_kind: str) -> tuple[DecisionKind, bool]:
    if action_kind in _INFORM_KINDS:
        return DecisionKind.INFORM, False
    # RECOMMEND kinds, and anything unrecognised, are treated as side-effectful:
    # confirm-first by default.
    return DecisionKind.RECOMMEND, True


def decide_situation(session: Session, scope: Scope, situation) -> list[Decision]:
    """Produce/refresh the decisions for one situation. Empty if it has no
    reasoning yet (reasoning always runs first in the pipeline)."""
    reasoning = session.execute(
        select(SituationReasoning).where(SituationReasoning.situation_id == situation.id)
    ).scalar_one_or_none()
    if reasoning is None:
        return []

    # The thing the situation is about, so the rationale can name it instead of
    # saying "one resource".
    entity_name = None
    if situation.primary_entity_id is not None:
        from app.models.entity import Entity

        anchor = session.get(Entity, situation.primary_entity_id)
        entity_name = anchor.display_name if anchor is not None else None

    memory = matching_memory(session, scope, situation)
    priority = reasoning.priority_score + (_MEMORY_BOOST if memory is not None else 0.0)
    # Said the way a person would say it. The numeric score stays on
    # `priority_score` for ordering and debugging; repeating it in the rationale
    # only ever produced copy like "Priority 147.0 (critical, cross-provider)",
    # which reads as a leaked internal rather than a reason.
    seen = memory.evidence.get("occurrence_count") if memory else None
    memory_note = (
        f" Sentinel has seen this {seen} times before, so it is ranked higher."
        if memory and seen
        else " This keeps happening, so it is ranked higher."
        if memory
        else ""
    )

    existing = {
        d.action_key: d
        for d in session.execute(select(Decision).where(Decision.situation_id == situation.id)).scalars().all()
    }
    desired_keys: set[str] = set()
    out: list[Decision] = []

    for item in reasoning.recommended_actions or []:
        action_kind = item.get("grounded_in", "unknown")
        action_text = item.get("action", f"Review the {action_kind}")
        kind, requires_confirmation = _classify(action_kind)
        # Why this is worth doing, in the user's terms: how serious it is, and
        # whether it spans more than one tool - which is the whole reason a
        # correlated situation outranks an isolated finding.
        reach = (
            "It spans several of your tools"
            if situation.cross_provider
            else f"It concerns {entity_name}"
            if entity_name
            else "It concerns one resource"
        )
        rationale = f"{_SEVERITY_PHRASE.get(situation.severity, 'Worth a look')}. {reach}.{memory_note}"
        desired_keys.add(action_kind)

        d = existing.get(action_kind)
        if d is None:
            d = Decision(
                workspace_id=situation.workspace_id, scope_key=scope.key, situation_id=situation.id,
                action_key=action_kind, status=DecisionStatus.PROPOSED,
            )
            session.add(d)
        # Never overwrite a human's decision on it.
        if d.status in (DecisionStatus.PROPOSED,):
            d.kind = kind
            d.action = action_text
            d.grounded_in = action_kind
            d.rationale = rationale
            d.requires_confirmation = requires_confirmation
            d.memory_informed = memory is not None
            d.memory_id = memory.id if memory is not None else None
            d.priority_score = round(priority, 2)
        out.append(d)

    # Drop proposals whose grounding disappeared (finding kind no longer present).
    for key, d in existing.items():
        if key not in desired_keys and d.status is DecisionStatus.PROPOSED:
            session.delete(d)

    session.flush()
    return out


def refresh_decisions(session: Session, scope: Scope) -> list[Decision]:
    """Decide over every open situation in a scope."""
    decisions: list[Decision] = []
    for sit in list_situations(session, scope.workspace_id, scope.key):
        decisions.extend(decide_situation(session, scope, sit))
    return decisions


def list_decisions(session: Session, scope: Scope, *, proposed_only: bool = True) -> list[Decision]:
    stmt = select(Decision).where(Decision.scope_key == scope.key)
    if proposed_only:
        stmt = stmt.where(Decision.status == DecisionStatus.PROPOSED)
    rows = session.execute(stmt).scalars().all()
    return sorted(rows, key=lambda d: -d.priority_score)


def set_decision_status(session: Session, decision_id, status: DecisionStatus) -> Decision | None:
    """Human management of a proposal (confirm / dismiss). Confirming records
    intent only - actual execution stays with the confirm-first action path;
    this engine never acts on the world itself."""
    d = session.get(Decision, decision_id)
    if d is None:
        return None
    d.status = status
    session.flush()
    return d
