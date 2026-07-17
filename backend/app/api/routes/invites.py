import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_workspace_membership
from app.models.invite import WorkspaceInvite
from app.models.team import Team
from app.models.user import User
from app.models.workspace import Role, Workspace
from app.schemas.invite import InviteAcceptResult, InviteCreate, InviteOut, InvitePreview
from app.services.invites import accept_invite, get_invite_by_token, validate_invite

router = APIRouter(tags=["invites"])


def _create_invite(session: Session, *, workspace_id: uuid.UUID, team_id: uuid.UUID | None, payload: InviteCreate, user: User) -> WorkspaceInvite:
    try:
        role = Role(payload.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {payload.role}")

    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours) if payload.expires_in_hours else None
    )
    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        team_id=team_id,
        created_by_user_id=user.id,
        role=role,
        expires_at=expires_at,
        max_uses=payload.max_uses,
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return invite


@router.post("/workspaces/{workspace_id}/invites", response_model=InviteOut, status_code=201)
def create_workspace_invite(
    workspace_id: uuid.UUID,
    payload: InviteCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkspaceInvite:
    require_workspace_membership(session, user, workspace_id)
    return _create_invite(session, workspace_id=workspace_id, team_id=None, payload=payload, user=user)


@router.post("/teams/{team_id}/invites", response_model=InviteOut, status_code=201)
def create_team_invite(
    team_id: uuid.UUID,
    payload: InviteCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkspaceInvite:
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    require_workspace_membership(session, user, team.workspace_id)
    return _create_invite(session, workspace_id=team.workspace_id, team_id=team_id, payload=payload, user=user)


@router.get("/invites/{token}", response_model=InvitePreview)
def preview_invite(token: str, session: Session = Depends(get_db)) -> InvitePreview:
    """Public - no auth required, so a link can be previewed before signing
    up/logging in, the way Discord shows a server preview pre-join."""
    invite = get_invite_by_token(session, token)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")

    valid, reason = validate_invite(invite)
    workspace = session.get(Workspace, invite.workspace_id)
    team = session.get(Team, invite.team_id) if invite.team_id else None
    inviter = session.get(User, invite.created_by_user_id)

    return InvitePreview(
        workspace_name=workspace.name if workspace else "Unknown workspace",
        team_name=team.name if team else None,
        invited_by_name=inviter.name if inviter else "Someone",
        valid=valid,
        reason_invalid=reason,
    )


@router.post("/invites/{token}/accept", response_model=InviteAcceptResult)
def accept_invite_route(
    token: str,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InviteAcceptResult:
    invite = get_invite_by_token(session, token)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")

    valid, reason = validate_invite(invite)
    if not valid:
        raise HTTPException(status_code=400, detail=reason)

    accept_invite(session, invite, user)
    return InviteAcceptResult(workspace_id=invite.workspace_id, team_id=invite.team_id)
