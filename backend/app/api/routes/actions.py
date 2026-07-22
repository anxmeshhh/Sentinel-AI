"""Agentic Actions: propose, approve, execute, audit.

    GET  /actions/catalog            what Sentinel is allowed to do here
    GET  /actions                    your own proposals and history
    POST /actions                    propose one (nothing happens yet)
    GET  /teams/{id}/actions         the channel's
    POST /teams/{id}/actions         propose one for the channel

    POST /actions/{id}/approve|reject|execute
    GET  /workspaces/audit/actions   what Sentinel changed here

Scope is derived server-side from the route, never accepted in the body: it
decides both what the action may touch and who is allowed to approve it.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id, require_channel_role
from app.models.action import Action
from app.models.team import ChannelRole, Team
from app.models.user import User
from app.models.workspace import Role
from app.schemas.action import ActionCatalogEntry, ActionCreate, ActionOut
from app.services.action_registry import (
    ActionRejected,
    ActionUnavailable,
    REGISTRY,
    available_actions,
)
from app.services.actions import (
    NotAuthorized,
    approve_action,
    audit_trail,
    execute_action,
    list_actions,
    propose_action,
    reject_action,
)

router = APIRouter(tags=["actions"])

_ANY_MEMBER = [ChannelRole.CHANNEL_ADMIN, ChannelRole.CHANNEL_MEMBER]


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, NotAuthorized):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ActionUnavailable):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/actions/catalog", response_model=list[ActionCatalogEntry])
def catalog(scope: str = "personal") -> list[ActionCatalogEntry]:
    """Exactly what Sentinel may do, including what it may not do yet.

    Unavailable entries are listed with their reason rather than hidden, so
    the boundary is legible: a provider action that needs a connection says
    so instead of silently not existing.
    """
    entries = [
        ActionCatalogEntry(
            key=s.key, label=s.label, risk=s.risk.value, scopes=list(s.scopes),
            external=s.external, needs_approval=s.needs_approval,
            available=s.available, unavailable_reason=s.unavailable_reason,
            requires_channel_admin=s.required_role == ChannelRole.CHANNEL_ADMIN,
        )
        for s in REGISTRY.values()
        if scope in s.scopes
    ]
    return sorted(entries, key=lambda e: (not e.available, e.risk, e.key))


# --- individual ------------------------------------------------------------


@router.get("/actions", response_model=list[ActionOut])
def my_actions(
    pending_only: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ActionOut]:
    return list_actions(session, f"personal:{user.id}", pending_only=pending_only)


@router.post("/actions", response_model=ActionOut, status_code=201)
def propose_my_action(
    payload: ActionCreate,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> ActionOut:
    """Propose an action in your own context. Nothing executes here."""
    try:
        return propose_action(
            session,
            workspace_id=workspace_id,
            scope_key=f"personal:{user.id}",
            action_type=payload.action_type,
            params=payload.params,
            user_id=user.id,
            reason=payload.reason,
            source_kind=payload.source_kind,
            source_id=payload.source_id,
        )
    except Exception as exc:
        raise _handle(exc) from exc


# --- channel ---------------------------------------------------------------


@router.get("/teams/{team_id}/actions", response_model=list[ActionOut])
def channel_actions(
    team_id: uuid.UUID,
    pending_only: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ActionOut]:
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    return list_actions(session, f"channel:{team_id}", pending_only=pending_only)


@router.post("/teams/{team_id}/actions", response_model=ActionOut, status_code=201)
def propose_channel_action(
    team_id: uuid.UUID,
    payload: ActionCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ActionOut:
    """Propose a shared action. Membership gets you this far; the action's own
    required role decides whether it may actually be proposed."""
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    team = session.get(Team, team_id)
    try:
        return propose_action(
            session,
            workspace_id=team.workspace_id,
            scope_key=f"channel:{team_id}",
            action_type=payload.action_type,
            params=payload.params,
            user_id=user.id,
            reason=payload.reason,
            source_kind=payload.source_kind,
            source_id=payload.source_id,
        )
    except Exception as exc:
        raise _handle(exc) from exc


# --- lifecycle -------------------------------------------------------------


def _action_or_404(session: Session, action_id: uuid.UUID) -> Action:
    action = session.get(Action, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Not found")
    return action


@router.post("/actions/{action_id}/approve", response_model=ActionOut)
def approve(
    action_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ActionOut:
    try:
        return approve_action(session, _action_or_404(session, action_id), user.id)
    except Exception as exc:
        raise _handle(exc) from exc


@router.post("/actions/{action_id}/reject", response_model=ActionOut)
def reject(
    action_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ActionOut:
    try:
        return reject_action(session, _action_or_404(session, action_id), user.id)
    except Exception as exc:
        raise _handle(exc) from exc


@router.post("/actions/{action_id}/execute", response_model=ActionOut)
def execute(
    action_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ActionOut:
    """Run an approved action. Safe to call twice - the second call finds a
    finished action and returns it unchanged rather than acting again."""
    try:
        return execute_action(session, _action_or_404(session, action_id), user.id)
    except Exception as exc:
        raise _handle(exc) from exc


# --- audit -----------------------------------------------------------------


@router.get("/workspaces/audit/actions", response_model=list[ActionOut])
def workspace_audit(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[ActionOut]:
    """What Sentinel actually changed in this workspace.

    Workspace admins only: the trail spans everyone's actions, so it answers
    "what did this system do here" - a question that belongs to whoever is
    responsible for the workspace, not to every member.
    """
    from app.models.workspace import Membership

    membership = session.query(Membership).filter_by(workspace_id=workspace_id, user_id=user.id).one_or_none()
    if membership is None or membership.role not in (Role.ORG_ADMIN, Role.SUPER_ADMIN):
        raise HTTPException(status_code=403, detail="Workspace admins only")
    return audit_trail(session, workspace_id)
