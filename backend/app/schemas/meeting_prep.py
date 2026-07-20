import uuid
from datetime import datetime

from pydantic import BaseModel


class BriefSourceOut(BaseModel):
    kind: str  # meeting | email | document | prior_meeting
    label: str
    url: str | None


class MeetingBriefOut(BaseModel):
    id: uuid.UUID
    title: str
    narrative: str
    prep_points: list[str]
    sources: list[BriefSourceOut]
    created_at: datetime
    cached: bool  # so the UI can honestly say "generated earlier" vs "just now"
