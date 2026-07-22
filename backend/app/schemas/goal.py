import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class GoalEvidenceItem(BaseModel):
    kind: str
    id: str
    title: str
    detail: str


class LinkedCommitmentOut(BaseModel):
    id: uuid.UUID
    what: str
    status: str
    owner_label: str | None
    due_at: str | None


class GoalOut(BaseModel):
    id: uuid.UUID
    title: str
    outcome: str | None
    due_at: datetime | None

    # FACT - computed from linked evidence, never model-assigned.
    health: str
    # None means "not measurable yet", which is a real answer rather than 0%.
    progress: float | None
    health_reasons: list[str]

    # INFERENCE + RECOMMENDATION - null until the state changes enough to be
    # worth explaining, or when the model was unreachable.
    assessment: str | None
    next_step: str | None
    llm_calls: int

    closed_at: datetime | None
    created_at: datetime


class GoalDetailOut(GoalOut):
    commitments: list[LinkedCommitmentOut]
    blockers: list[GoalEvidenceItem]
    risks: list[GoalEvidenceItem]


class GoalCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    outcome: str | None = Field(default=None, max_length=2000)
    due_at: datetime | None = None


class GoalLinkCreate(BaseModel):
    commitment_id: uuid.UUID
