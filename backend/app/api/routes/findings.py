import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_workspace_id
from app.repositories.findings import AgentFindingRepository
from app.schemas.finding import FindingOut

router = APIRouter(prefix="/findings", tags=["findings"])


@router.get("/{finding_id}", response_model=FindingOut)
def get_finding(
    finding_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> FindingOut:
    finding = AgentFindingRepository(session, workspace_id).get(finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding
