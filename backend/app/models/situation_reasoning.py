"""The Reasoning Engine's output - Intelligence Core, Phase 5.

One reasoning per Situation: the deterministic priority and recommended actions
(the SOURCE OF TRUTH), plus an optional LLM-written explanation that is strictly
an explanation of the prepared context - never a decision, never a fact the
system did not already establish deterministically.

Cached and regenerated only when the situation's evidence fingerprint changes,
so a stable situation costs zero tokens. If the LLM is unavailable the row still
exists with its deterministic fields intact and ``source = 'deterministic'`` -
reasoning degrades to its floor, it never fails.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk, utcnow


class SituationReasoning(Base, UUIDPk, TimestampMixin):
    __tablename__ = "situation_reasonings"
    __table_args__ = (UniqueConstraint("situation_id", name="uq_reasoning_situation"),)

    situation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("correlated_situations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # --- DETERMINISTIC: the source of truth. Never model-written. ---
    # A score derived from severity, corroboration, cross-provider span and
    # trajectory. Ranking is a sort over this, so the LLM can never reorder
    # what matters.
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    # [{"action": "...", "grounded_in": "<finding kind>"}] - derived from the
    # real member finding kinds, so every recommendation traces to evidence.
    recommended_actions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    # --- EXPLANATION: the LLM's reading of the prepared context. Empty (and
    # source='deterministic') when the LLM was unavailable or unused. ---
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_it_matters: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="deterministic")  # deterministic | llm

    # Regenerate only when this changes - the rate-limit discipline.
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    reasoned_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
