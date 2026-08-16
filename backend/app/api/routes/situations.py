"""Correlated Situations - the read side.

Situations were already computed and stored by the Situation Engine; until now
they were only reachable narrowed to one service, through
`/workspace/{service}/intelligence`. That made the product's most valuable
output the one thing a person could not open directly.

Everything here is READ-ONLY and derived: it assembles what the engines already
wrote (the situation, its member findings, the reasoning, the memory that
justifies "this keeps happening", and the decisions grounded in it) into the one
shape a Situation page needs. No detection, no correlation, no LLM call - a
route that computed intelligence would be a second pipeline, which is exactly
what the architecture forbids.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.models.action import Action
from app.models.correlated_situation import Situation, SituationFinding, SituationStatus
from app.models.decision import Decision, DecisionStatus
from app.models.entity import Entity, EntityMention
from app.models.memory import Memory, MemoryStatus
from app.models.situation_reasoning import SituationReasoning
from app.models.user import User
from app.services.findings import list_findings
from app.services.investigation import personal_scope

router = APIRouter(prefix="/situations", tags=["situations"])


def _situation_row(session: Session, sit: Situation) -> dict:
    entity = session.get(Entity, sit.primary_entity_id) if sit.primary_entity_id else None
    members = session.execute(
        select(SituationFinding).where(SituationFinding.situation_id == sit.id)
    ).scalars().all()
    return {
        "id": str(sit.id),
        "title": sit.title,
        "entity": entity.display_name if entity else None,
        "entity_kind": entity.kind.value if entity else None,
        "severity": sit.severity,
        "status": sit.status.value,
        "member_count": sit.member_count,
        "cross_provider": sit.cross_provider,
        "occurrence_count": sit.occurrence_count,
        "providers": sorted({m.provider for m in members if m.provider}),
        "first_seen_at": sit.first_seen_at.isoformat() if sit.first_seen_at else None,
        "last_activity_at": sit.last_activity_at.isoformat() if sit.last_activity_at else None,
        "resolved_at": sit.resolved_at.isoformat() if sit.resolved_at else None,
    }


@router.get("")
def list_situations_for_scope(
    status: str | None = None,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Every situation in the caller's own scope, worst and most recent first."""
    scope = personal_scope(session, workspace_id, user.id)
    query = select(Situation).where(
        Situation.workspace_id == workspace_id,
        Situation.scope_key == scope.key,
    )
    if status == "open":
        query = query.where(Situation.status == SituationStatus.OPEN)
    elif status == "resolved":
        query = query.where(Situation.status == SituationStatus.RESOLVED)

    rank = {"critical": 0, "review": 1, "reminder": 2}
    rows = session.execute(query).scalars().all()
    rows.sort(key=lambda s: (rank.get(s.severity, 99), -(s.last_activity_at.timestamp() if s.last_activity_at else 0)))
    return [_situation_row(session, s) for s in rows]


@router.get("/{situation_id}")
def situation_detail(
    situation_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """One situation with everything needed to understand and act on it."""
    scope = personal_scope(session, workspace_id, user.id)
    sit = session.get(Situation, situation_id)
    # Scope is re-checked here, not just the workspace: a situation belongs to
    # one person's or one channel's view, and reading across that boundary is
    # exactly what the scope model exists to prevent.
    if sit is None or sit.workspace_id != workspace_id or sit.scope_key != scope.key:
        raise HTTPException(status_code=404, detail="Situation not found")

    members = session.execute(
        select(SituationFinding).where(SituationFinding.situation_id == sit.id)
    ).scalars().all()
    member_ids = [m.finding_id for m in members]

    # The canonical findings, so titles/evidence/urls match the rest of the app
    # rather than being re-derived here.
    by_id = {f.id: f for f in list_findings(session, scope)}
    findings = []
    for m in members:
        f = by_id.get(m.finding_id)
        findings.append({
            "id": m.finding_id,
            "provider": m.provider,
            "tier": m.tier,
            "source": m.finding_source,
            "title": f.title if f else None,
            "why": f.summary if f else None,
            "url": f.evidence_url if f else None,
            "occurred_at": f.occurred_at.isoformat() if f and f.occurred_at else None,
            "evidence": (f.evidence or []) if f else [],
            # A member whose finding has since resolved is still part of the
            # record; the UI shows it dimmed rather than silently dropping it.
            "live": f is not None,
        })

    reasoning = session.execute(
        select(SituationReasoning).where(SituationReasoning.situation_id == sit.id)
    ).scalar_one_or_none()

    # Memory is keyed on the situation's dedupe_key - that is what makes
    # "this keeps happening" attach to the same situation across occurrences.
    memory = session.execute(
        select(Memory).where(
            Memory.workspace_id == workspace_id,
            Memory.scope_key == scope.key,
            Memory.subject_key == sit.dedupe_key,
            Memory.status == MemoryStatus.ACTIVE,
        )
    ).scalar_one_or_none()

    decisions = session.execute(
        select(Decision).where(
            Decision.situation_id == sit.id,
            Decision.status == DecisionStatus.PROPOSED,
        ).order_by(Decision.priority_score.desc())
    ).scalars().all()

    # Actions raised from this situation - the "what was already done" trail.
    actions = session.execute(
        select(Action).where(
            Action.workspace_id == workspace_id,
            Action.source_id == sit.id,
        ).order_by(Action.created_at.desc())
    ).scalars().all()

    entities = []
    if member_ids:
        seen: set[uuid.UUID] = set()
        for mention in session.execute(
            select(EntityMention).where(
                EntityMention.workspace_id == workspace_id,
                EntityMention.scope_key == scope.key,
                EntityMention.finding_id.in_(member_ids),
            )
        ).scalars().all():
            if mention.entity_id in seen:
                continue
            seen.add(mention.entity_id)
            ent = session.get(Entity, mention.entity_id)
            if ent is not None:
                entities.append({
                    "id": str(ent.id),
                    "kind": ent.kind.value,
                    "name": ent.display_name,
                    "role": mention.role.value,
                })

    anchor = session.get(Entity, sit.primary_entity_id) if sit.primary_entity_id else None
    return {
        **_situation_row(session, sit),
        # Deterministic, never LLM prose: this sentence is the trust anchor that
        # proves the connection is a fact rather than a guess.
        "why_connected": (
            f"All {len(members)} concern the same "
            f"{anchor.kind.value if anchor else 'resource'}, {anchor.display_name}."
            if anchor else "These findings share a common resource."
        ),
        "findings": findings,
        "entities": entities,
        "reasoning": {
            "explanation": reasoning.explanation,
            "recommended_actions": reasoning.recommended_actions or [],
        } if reasoning else None,
        "memory": {
            "id": str(memory.id),
            "summary": memory.summary,
            "observation_count": memory.observation_count,
            "strength": memory.strength,
            "first_observed_at": memory.first_observed_at.isoformat() if memory.first_observed_at else None,
        } if memory else None,
        "decisions": [
            {
                "id": str(d.id),
                "kind": d.kind.value,
                "action": d.action,
                "action_key": d.action_key,
                "grounded_in": d.grounded_in,
                "rationale": d.rationale,
                "requires_confirmation": d.requires_confirmation,
                "memory_informed": d.memory_informed,
                "priority_score": d.priority_score,
            }
            for d in decisions
        ],
        "actions": [
            {
                "id": str(a.id),
                "action_type": a.action_type,
                "status": a.status.value,
                "risk": a.risk.value,
                "verification": a.verification,
                "executed_at": a.executed_at.isoformat() if a.executed_at else None,
                "undone_at": a.undone_at.isoformat() if a.undone_at else None,
                "undo_result": a.undo_result,
            }
            for a in actions
        ],
    }
