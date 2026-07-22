import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CommitmentEvidenceOut(BaseModel):
    signal_id: str
    kind: str
    title: str
    actor: str | None
    occurred_at: str
    url: str | None
    relation: str


class CommitmentOut(BaseModel):
    id: uuid.UUID
    source: str
    status: str

    what: str
    owner_label: str | None
    due_at: datetime | None

    evidence: list[CommitmentEvidenceOut]
    last_progress_at: datetime | None
    confidence: float

    resolved_at: datetime | None
    resolution_reason: str | None
    created_at: datetime


class CommitmentCreate(BaseModel):
    what: str = Field(min_length=2, max_length=500)
    due_at: datetime | None = None
    owner_label: str | None = Field(default=None, max_length=200)


class CommitmentResolve(BaseModel):
    reason: str = Field(default="Marked done", max_length=500)
