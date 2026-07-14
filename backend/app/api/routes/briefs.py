import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_workspace_id
from app.repositories.briefs import BriefRepository
from app.repositories.findings import FindingRepository
from app.schemas.brief import BriefOut, BriefSummaryOut
from app.schemas.finding import FindingOut

router = APIRouter(prefix="/briefs", tags=["briefs"])


@router.get("/latest", response_model=BriefOut)
def latest_brief(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> BriefOut:
    brief = BriefRepository(session, workspace_id).latest()
    if brief is None:
        raise HTTPException(status_code=404, detail="No brief has been generated yet")
    findings = FindingRepository(session, workspace_id).for_run(brief.run_id)
    return BriefOut(
        id=brief.id,
        run_id=brief.run_id,
        generated_at=brief.generated_at,
        narrative=brief.narrative,
        top_finding_ids=brief.top_finding_ids,
        data_freshness=brief.data_freshness,
        findings=[FindingOut.model_validate(f) for f in findings],
    )


@router.get("", response_model=list[BriefSummaryOut])
def brief_history(
    limit: int = 30,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list:
    return BriefRepository(session, workspace_id).history(limit=limit)
