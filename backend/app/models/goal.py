"""A goal: a desired outcome, and whether the evidence says it will happen.

Not a project-management object. There are no boards, sprints, dependency
graphs or percent-complete sliders - a goal exists to point Sentinel's
existing intelligence at one outcome and answer five questions: what are we
trying to achieve, how are we doing, what is blocking us, what is at risk,
and what should we do next.

## Health is computed, never asserted by a model

`health` and `progress` are derived from linked commitments and the deadline
by `services/goals.py`. The model is allowed to *explain* the resulting
state and never to decide it - "this goal is 73% complete" is exactly the
false precision this module has to avoid. When nothing is linked, progress is
NULL and the UI says progress cannot yet be determined, rather than showing
a confident zero.

## Links are explicit

A goal is connected to commitments by a person saying so, not by keyword
similarity. Guessing which commitments belong to "Launch Product V2" would
put the whole health calculation on a foundation of string matching. Active
situations in the same scope are surfaced alongside as *risks in this
context* - which is an honest description of what they are, and stops short
of claiming they caused anything.

## Scope

`scope_key` is "personal:{user_id}" or "channel:{team_id}", as everywhere
else. A private goal is evaluated only against private evidence, and a
channel goal only against what that channel is authorized to see - so a
member's private commitments can never move a team goal's health.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Enum, Float, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class GoalHealth(str, enum.Enum):
    # Nothing linked yet, so nothing can honestly be said about progress.
    UNKNOWN = "unknown"
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    BLOCKED = "blocked"
    ACHIEVED = "achieved"  # a person said so
    ABANDONED = "abandoned"  # a person said so


class Goal(Base, UUIDPk, TimestampMixin):
    __tablename__ = "goals"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # What "done" means, in the author's words. Feeds the explanation prompt
    # so the model reasons about the stated outcome rather than the title.
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # --- FACT: computed from linked evidence, never model-assigned.
    health: Mapped[GoalHealth] = mapped_column(
        Enum(GoalHealth, name="goal_health"), nullable=False, default=GoalHealth.UNKNOWN
    )
    # 0..1, or NULL when nothing measurable is linked. NULL is a real answer
    # here - "progress cannot yet be determined" beats a confident 0%.
    progress: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Why the health is what it is, as short factual strings ("2 linked
    # commitments overdue"). Deterministic, so a user can check the reasoning
    # without having to trust the prose that accompanies it.
    health_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # --- INFERENCE + RECOMMENDATION: the model's reading of the above.
    # Empty until the state changes enough to be worth explaining.
    assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_calls: Mapped[int] = mapped_column(nullable=False, default=0)
    # Bumped when the computed state changes; the explanation is only
    # regenerated when it does, so a stable goal costs nothing to re-read.
    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class GoalCommitment(Base, UUIDPk, TimestampMixin):
    """An explicit link between a goal and a commitment.

    Explicit because health depends on it. Inferring these from wording would
    mean a goal's health was ultimately decided by string overlap, and a
    single wrong link would silently move a team's launch to BLOCKED.
    """

    __tablename__ = "goal_commitments"
    __table_args__ = (UniqueConstraint("goal_id", "commitment_id", name="uq_goal_commitment"),)

    goal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    commitment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("commitments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    linked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
