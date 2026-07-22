import uuid
from datetime import datetime

from pydantic import BaseModel


class EvidenceOut(BaseModel):
    """One verified fact, retrieved from Signals. Never model-generated."""

    signal_id: str
    kind: str
    title: str
    actor: str | None
    occurred_at: str | None
    url: str | None
    relation: str
    relation_label: str


class InvestigationOut(BaseModel):
    id: uuid.UUID
    attention_item_id: uuid.UUID
    title: str

    # AI inference over the evidence below - labelled as such in the UI.
    what_happened: str
    why_it_matters: str
    contributing_factors: list[str]
    next_steps: list[str]
    confidence: float

    evidence: list[EvidenceOut]
    llm_calls: int
    created_at: datetime
