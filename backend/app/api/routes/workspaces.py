import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_workspace_membership
from app.core.bootstrap import provision_personal_workspace_for_user
from app.core.slugs import unique_slug
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.workspace import WorkspaceCreate, WorkspaceMemberOut, WorkspaceOut

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WorkspaceOut]:
    """Phase 1.6: the authenticated user's own workspaces, via their real
    Memberships - no longer the fixed bootstrap pair every caller used to
    see regardless of who (or whether anyone) was logged in.
    """
    provision_personal_workspace_for_user(session, user)  # safety net for pre-existing accounts

    rows = session.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id)
    ).all()
    return [
        WorkspaceOut(id=w.id, name=w.name, slug=w.slug, kind=w.kind.value, role=role.value, is_demo=w.is_demo)
        for w, role in rows
    ]


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(
    payload: WorkspaceCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Workspace:
    """The "Create Workspace" step of IA.md v2 §2.2 - the actual "make a new
    Discord server" action. Creator becomes Owner/Admin (Role.ORG_ADMIN, the
    closest existing role until the v2 role set replaces this one - see
    IA.md v2 §8.2 point 4).
    """
    workspace = Workspace(name=payload.name, slug=unique_slug(payload.name), kind=WorkspaceKind.ORGANIZATION)
    session.add(workspace)
    session.flush()

    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.ORG_ADMIN))
    session.commit()
    session.refresh(workspace)
    return workspace


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberOut])
def list_workspace_members(
    workspace_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WorkspaceMemberOut]:
    """Phase 2o: the member picker in the Create Channel modal needs the
    parent Group's roster - any workspace member may see it (same openness
    as Discord's member list), it exposes nothing beyond name/email/role.
    """
    require_workspace_membership(session, user, workspace_id)
    rows = session.execute(
        select(User.id, User.name, User.email, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == workspace_id)
    ).all()
    return [WorkspaceMemberOut(user_id=uid, name=name, email=email, role=role.value) for uid, name, email, role in rows]
