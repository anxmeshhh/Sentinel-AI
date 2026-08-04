"""Decisions API - Sentinel's grounded, confirm-first proposals (Phase 7).

    GET  /decisions              proposed actions in your scope, priority-first
    POST /decisions/{id}/confirm record approval (does NOT execute)
    POST /decisions/{id}/dismiss dismiss the proposal

CONFIRM-FIRST: confirming a decision only records intent. Nothing side-effectful
runs here - execution stays with the existing action path. Scope is derived
server-side.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.models.decision import Decision, DecisionStatus
from app.models.user import User
from app.services.decision_engine import list_decisions, set_decision_status
from app.services.investigation import personal_scope

router = APIRouter(prefix="/decisions", tags=["decisions"])


def _out(d: Decision) -> dict:
    return {
        "id": str(d.id),
        "situation_id": str(d.situation_id),
        "kind": d.kind.value,
        "action": d.action,
        "grounded_in": d.grounded_in,
        "rationale": d.rationale,
        "requires_confirmation": d.requires_confirmation,
        "memory_informed": d.memory_informed,
        "priority_score": d.priority_score,
        "status": d.status.value,
    }


@router.get("")
def get_decisions(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[dict]:
    scope = personal_scope(session, workspace_id, user.id)
    return [_out(d) for d in list_decisions(session, scope)]


def _resolve(session: Session, workspace_id: uuid.UUID, user: User, decision_id: uuid.UUID) -> Decision:
    scope = personal_scope(session, workspace_id, user.id)
    d = session.get(Decision, decision_id)
    if d is None or d.scope_key != scope.key:
        raise HTTPException(status_code=404, detail="Decision not found")
    return d


@router.post("/{decision_id}/confirm")
def confirm(
    decision_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """Record approval only. Execution remains confirm-first, handled elsewhere."""
    _resolve(session, workspace_id, user, decision_id)
    d = set_decision_status(session, decision_id, DecisionStatus.CONFIRMED)
    session.commit()
    return _out(d)


@router.post("/{decision_id}/dismiss")
def dismiss(
    decision_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    _resolve(session, workspace_id, user, decision_id)
    d = set_decision_status(session, decision_id, DecisionStatus.DISMISSED)
    session.commit()
    return _out(d)
