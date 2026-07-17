from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.bootstrap import provision_personal_workspace_for_user
from app.models.user import User
from app.models.workspace import Membership, Workspace
from app.schemas.workspace import WorkspaceOut

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
