import uuid
from datetime import datetime

from pydantic import BaseModel


class RunTrigger(BaseModel):
    connection_id: uuid.UUID


class RunOut(BaseModel):
    id: uuid.UUID
    status: str
    triggered_by: str
    started_at: datetime
    finished_at: datetime | None
    error: str | None

    model_config = {"from_attributes": True}
