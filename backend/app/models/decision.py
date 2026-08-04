"""The Decision Engine's object - Intelligence Core, Phase 7.

A Decision is a grounded, safety-classified PROPOSAL for what to do about a
situation. It consumes the deterministic Reasoning (priority, recommended
actions) and Memory (has this recurred?) and Context - never raw data, never an
LLM as the source of truth. Memory's influence is recorded explicitly
(``memory_informed`` + the rationale), so a boosted priority is never opaque.

Confirm-first is preserved absolutely: a decision is a PROPOSED recommendation.
Nothing side-effectful executes here. Anything that would act on the world
carries ``requires_confirmation = True`` and stays PROPOSED until a human
confirms it through the existing action path - this engine never sends, closes,
posts or deletes anything.

Traceable: ``situation_id`` -> Situation -> Finding -> Signal -> provider
evidence; ``memory_id`` -> the learned pattern that shaped it.
"""

import enum
import uuid

from sqlalchemy import Boolean, Enum, Float, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk


class DecisionKind(str, enum.Enum):
    INFORM = "inform"  # a read/attention nudge - no side effect (review, prepare, check)
    RECOMMEND = "recommend"  # a suggested action that would act on the world - requires confirmation


class DecisionStatus(str, enum.Enum):
    PROPOSED = "proposed"  # the only state this engine writes - nothing acts without a human
    CONFIRMED = "confirmed"  # a human approved it (execution handled by the confirm-first action path)
    DISMISSED = "dismissed"
    EXECUTED = "executed"


class Decision(Base, UUIDPk, TimestampMixin):
    __tablename__ = "decisions"
    # One live decision per (situation, action) - it evolves, never duplicates.
    __table_args__ = (UniqueConstraint("situation_id", "action_key", name="uq_decision_situation_action"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    situation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("correlated_situations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The learned pattern that shaped this decision, if any - the Memory link.
    memory_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True, index=True
    )

    kind: Mapped[DecisionKind] = mapped_column(Enum(DecisionKind, name="decision_kind"), nullable=False)
    # Stable identity of the action within a situation (its grounded finding kind).
    action_key: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(500), nullable=False)
    grounded_in: Mapped[str] = mapped_column(String(100), nullable=False)  # the finding kind / "memory"
    rationale: Mapped[str] = mapped_column(Text, nullable=False)  # deterministic: priority + memory influence

    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    memory_informed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    status: Mapped[DecisionStatus] = mapped_column(Enum(DecisionStatus, name="decision_status"), nullable=False, default=DecisionStatus.PROPOSED)
