import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.finding import FindingOut


class BriefOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    generated_at: datetime
    narrative: str
    top_finding_ids: list[str]
    data_freshness: dict
    findings: list[FindingOut] = []

    model_config = {"from_attributes": True}


class BriefSummaryOut(BaseModel):
    id: uuid.UUID
    generated_at: datetime
    narrative: str

    model_config = {"from_attributes": True}
