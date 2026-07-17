from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.bootstrap import provision_personal_workspace_for_user
from app.core.slugs import unique_slug
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.workspace import WorkspaceCreate, WorkspaceOut

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

    workspaces = session.execute(
        select(Workspace).join(Membership, Membership.workspace_id == Workspace.id).where(Membership.user_id == user.id)
    ).scalars().all()
    return [WorkspaceOut.model_validate(w) for w in workspaces]


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
