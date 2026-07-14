import uuid
from datetime import datetime

from pydantic import BaseModel


class FindingOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    agent: str
    type: str
    severity: float
    confidence: float
    summary: str
    root_cause: str
    suggested_action: str
    evidence: dict
    created_at: datetime

    model_config = {"from_attributes": True}
