import uuid
from datetime import datetime

from pydantic import BaseModel


class SituationEvidenceOut(BaseModel):
    """FACT. Retrieved from Signals, never model-written."""

    signal_id: str
    kind: str
    title: str
    actor: str | None
    occurred_at: str
    url: str | None
    relation: str


class SituationOut(BaseModel):
    id: uuid.UUID
    situation_key: str
    kind: str
    status: str
    title: str

    evidence: list[SituationEvidenceOut]
    evidence_count: int
    first_seen_at: datetime
    last_evidence_at: datetime

    # Deterministic scores - not model-assigned, so the model cannot talk
    # itself into a higher place in the list.
    importance: float
    confidence: float

    # INFERENCE + RECOMMENDATION. Null when the situation has not earned an
    # LLM call, or when the model was unreachable; the evidence above stands
    # on its own either way.
    what_is_developing: str | None
    why_it_matters: str | None
    suggested_next_steps: list[str]

    llm_calls: int

    # The AttentionItem one of this situation's signals also produced, if any.
    # Investigate This works on attention items, so this is what makes
    # "situation -> deeper investigation" a real link rather than a button
    # that has to invent its own workflow. Null when no evidence signal has a
    # corresponding item, and the UI then omits the action rather than
    # offering something that cannot work.
    investigatable_item_id: uuid.UUID | None = None
