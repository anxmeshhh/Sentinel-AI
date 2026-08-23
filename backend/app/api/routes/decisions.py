"""Decisions API - Sentinel's grounded, confirm-first proposals (Phase 7).

    GET  /decisions              proposed actions in your scope, priority-first
    POST /decisions/{id}/confirm record approval (does NOT execute)
    POST /decisions/{id}/dismiss dismiss the proposal

    GET  /teams/{id}/decisions   the same, for one channel's scope

CONFIRM-FIRST: confirming a decision only records intent. Nothing side-effectful
runs here - execution stays with the existing action path. Scope is derived
server-side.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id, require_channel_role
from app.models.action import ActionStatus
from app.models.decision import Decision, DecisionStatus
from app.models.team import ChannelRole
from app.models.user import User
from app.services.decision_engine import list_decisions, set_decision_status
from app.services.action_registry import ActionRejected
from app.services.actions import execute_action, propose_action
from app.services.investigation import channel_scope, personal_scope

router = APIRouter(prefix="/decisions", tags=["decisions"])

# The channel-scoped read lives on a second, un-prefixed router because its
# path is /teams/..., not /decisions/... - the same shape goals.py uses. Both
# are registered in main.py.
channel_router = APIRouter(tags=["decisions"])

_ANY_MEMBER = [ChannelRole.CHANNEL_ADMIN, ChannelRole.CHANNEL_MEMBER]


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


@channel_router.get("/teams/{team_id}/decisions")
def get_channel_decisions(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """A channel's own proposed decisions.

    The Decision Engine already writes these: refresh_decisions runs for every
    active scope on each sync, channels included - there was simply no route
    to read a channel's, so the rows existed and were unreachable. This adds
    the read and nothing else: same engine, same ordering, same shape as the
    personal list, with the scope taken from the channel rather than the
    caller so a member's private decisions can never surface here.
    """
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    return [_out(d) for d in list_decisions(session, channel_scope(session, team_id))]


def _resolve(session: Session, workspace_id: uuid.UUID, user: User, decision_id: uuid.UUID) -> Decision:
    scope = personal_scope(session, workspace_id, user.id)
    d = session.get(Decision, decision_id)
    if d is None or d.scope_key != scope.key:
        raise HTTPException(status_code=404, detail="Decision not found")
    return d


def _run_decision_action(
    session: Session, workspace_id: uuid.UUID, user: User, decision: Decision, action_type: str
) -> dict:
    """Confirm and dismiss leave through the Action Registry.

    Confirming still records intent and nothing else - the registry does not
    change that, it records who recorded it, verifies the status landed, and
    makes it undoable. Execution of the underlying work remains confirm-first
    on its own action path.
    """
    try:
        action = propose_action(
            session,
            workspace_id=workspace_id,
            scope_key=decision.scope_key,
            action_type=action_type,
            params={"decision_id": str(decision.id)},
            user_id=user.id,
            reason=f"{action_type} from the decisions surface",
            source_kind="decision",
            source_id=decision.id,
        )
        action = execute_action(session, action, user.id)
    except ActionRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if action.status is ActionStatus.FAILED:
        raise HTTPException(status_code=400, detail=action.error or "That proposal could not be updated")
    session.refresh(decision)
    return _out(decision)


@router.post("/{decision_id}/confirm")
def confirm(
    decision_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    """Record approval only. Execution remains confirm-first, handled elsewhere."""
    decision = _resolve(session, workspace_id, user, decision_id)
    return _run_decision_action(session, workspace_id, user, decision, "decision.confirm")


@router.post("/{decision_id}/dismiss")
def dismiss(
    decision_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    decision = _resolve(session, workspace_id, user, decision_id)
    return _run_decision_action(session, workspace_id, user, decision, "decision.dismiss")
