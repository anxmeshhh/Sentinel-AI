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
    # Exactly one of these is set - an investigation is anchored on either an
    # attention item or a proactive situation.
    attention_item_id: uuid.UUID | None = None
    situation_id: uuid.UUID | None = None
    commitment_id: uuid.UUID | None = None
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
