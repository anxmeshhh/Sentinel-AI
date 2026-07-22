"""A commitment: something someone said would happen, tracked until it does.

Not a task manager. The question this answers is "what did we say would
happen, and is it actually happening?" - so a Commitment always carries the
*evidence* it came from, and its lifecycle is driven by evidence and time
rather than by someone remembering to tick a box.

## Where commitments come from

    MANUAL     a person wrote it down ("remind me to review this by Friday").
               Fully available today.
    TRACKED    derived deterministically from a structured signal that has an
               owner, a subject and an observable completion state - a GitHub
               issue or PR assigned to someone. Resolution is then a fact
               (the issue closed), not an inference.

There is deliberately no "extracted from prose" source. Commitments live in
message bodies, and this codebase never stores them; measured against the
real corpus, email *subjects* contained 0 promise statements in 190 messages
and the mailbox held no sent mail at all, so "what did I promise" is not
answerable from what exists. Building an extractor for it would be inventing
a capability. See scripts/audit_commitments.py for the measurement and
PHASES.md for what would unblock it.

## Scope

`scope_key` is "personal:{user_id}" or "channel:{team_id}", exactly as for
Situations and Investigations. A private commitment and a team commitment are
different records even when they describe the same work, so a personal
promise can never surface as team intelligence.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Enum, Float, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class CommitmentSource(str, enum.Enum):
    MANUAL = "manual"  # a person stated it
    TRACKED = "tracked"  # derived from a structured signal with an owner


class CommitmentStatus(str, enum.Enum):
    PENDING = "pending"  # live, not close to its date (or has no date)
    DUE_SOON = "due_soon"  # inside the horizon
    AT_RISK = "at_risk"  # due soon AND no progress evidence for a while
    OVERDUE = "overdue"  # past its date, still unresolved
    RESOLVED = "resolved"  # evidence says it happened, or a person said so
    DISMISSED = "dismissed"  # a person said it doesn't matter


class Commitment(Base, UUIDPk, TimestampMixin):
    __tablename__ = "commitments"
    __table_args__ = (
        # One row per underlying commitment per scope. As with Situations,
        # this is what makes re-detection evolve a record rather than pile up
        # duplicates, enforced by the database rather than by the detector.
        UniqueConstraint("scope_key", "commitment_key", name="uq_commitment_scope_key"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    commitment_key: Mapped[str] = mapped_column(String(300), nullable=False)

    source: Mapped[CommitmentSource] = mapped_column(Enum(CommitmentSource, name="commitment_source"), nullable=False)
    status: Mapped[CommitmentStatus] = mapped_column(
        Enum(CommitmentStatus, name="commitment_status"), nullable=False, default=CommitmentStatus.PENDING
    )

    # WHAT.
    what: Mapped[str] = mapped_column(String(500), nullable=False)
    # WHO. A display label ("rahul", "Backend Team") rather than a user id:
    # the owner is usually an external account name, and resolving it to a
    # Sentinel user would be a guess. `owner_user_id` is set only when the
    # commitment is genuinely about a known Sentinel user.
    owner_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # WHEN. Nullable: "someone should look at this eventually" is still worth
    # tracking, it just never becomes DUE_SOON or OVERDUE.
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # WHY SENTINEL IS TRACKING IT - the signals behind it, same shape as a
    # Situation's evidence. Empty for a manual commitment, which is its own
    # evidence.
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # The signal a TRACKED commitment was derived from, so progress and
    # resolution can be re-read from the source rather than guessed.
    source_signal_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("signals.id", ondelete="SET NULL"), nullable=True
    )
    # When the source last showed any activity. Drives AT_RISK, and is what
    # makes "at risk" an observation rather than a mood.
    last_progress_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # How it ended, in plain words - "the issue was closed", "marked done by
    # Priya". A resolution with no stated reason is a resolution nobody can
    # check.
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
