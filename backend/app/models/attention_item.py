"""Phase 2p: the AttentionItem - Sentinel's core actionable primitive.

One row = one thing the user should act on, unified across every source
(an important email, an imminent meeting, a stale PR, an agent finding, a
manually-created reminder). This is deliberately a *materialized* list with
its own lifecycle state, not a live query over Signals: "done", "snoozed
until Monday", and "dismissed" are user decisions that must survive every
re-detection pass - a pure view could never remember them.

Detection is deterministic (services/attention_engine.py) per the
codebase-wide pattern: rules find candidates, and the `why` line is a
factual template ("starred, unread, arrived 2 days ago") - precise, zero
LLM tokens, never hallucinated. The LLM budget is spent where AI genuinely
adds value: Catch-Me-Up narration and on-demand investigation (Phase 2q).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, Float, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class AttentionType(str, enum.Enum):
    IMPORTANT_EMAIL = "important_email"
    UPCOMING_MEETING = "upcoming_meeting"
    STALE_PR = "stale_pr"
    FINDING = "finding"
    MANUAL = "manual"


class AttentionState(str, enum.Enum):
    NEW = "new"
    DONE = "done"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"


class AttentionOrigin(str, enum.Enum):
    DETECTED = "detected"  # produced by a detector - re-detection may update/auto-resolve it
    MANUAL = "manual"  # user-created - detectors never touch it


class AttentionItem(Base, UUIDPk, TimestampMixin):
    __tablename__ = "attention_items"
    # The dedupe key is what makes re-running detectors safe: the same
    # underlying fact (same email, same meeting occurrence, same PR) always
    # maps to the same row, so refreshes update in place instead of
    # stacking duplicates - and a DONE/DISMISSED row stays resolved instead
    # of being resurrected every sync.
    __table_args__ = (UniqueConstraint("workspace_id", "dedupe_key", name="uq_attention_workspace_dedupe"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)

    type: Mapped[AttentionType] = mapped_column(Enum(AttentionType, name="attention_type"), nullable=False)
    origin: Mapped[AttentionOrigin] = mapped_column(Enum(AttentionOrigin, name="attention_origin"), nullable=False)
    state: Mapped[AttentionState] = mapped_column(
        Enum(AttentionState, name="attention_state"), nullable=False, default=AttentionState.NEW, server_default=AttentionState.NEW.name
    )

    source_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)  # gmail/google_calendar/github/agent; None for manual
    dedupe_key: Mapped[str] = mapped_column(String(300), nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    why: Mapped[str] = mapped_column(String(500), nullable=False)  # factual, template-generated - see module docstring
    evidence_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # external "Open in ..." link, or internal /findings/{id}

    priority: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)  # 0..1, drives sort order
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # meetings: start time; manual: optional deadline
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
