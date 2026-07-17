from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.bootstrap import get_or_create_default_workspace, get_or_create_personal_workspace
from app.schemas.workspace import WorkspaceOut

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(session: Session = Depends(get_db)) -> list[WorkspaceOut]:
    """Phase 1.5: the fixed two-workspace set for the single implicit user.
    Phase 2 replaces this with "workspaces this authenticated user belongs
    to" - the response shape doesn't need to change, only how it's computed.
    """
    personal = get_or_create_personal_workspace(session)
    org = get_or_create_default_workspace(session)
    return [
        WorkspaceOut.model_validate(personal),
        WorkspaceOut.model_validate(org),
    ]
