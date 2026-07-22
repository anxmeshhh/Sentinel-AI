"""An action Sentinel proposes, a person approves, and the server executes.

The shape of this table is the safety model. Everything needed to answer
"what happened, who allowed it, and did it actually work" is a column, and
nothing that would be dangerous to keep is stored at all - no tokens, no
message bodies, no provider credentials.

## Why proposal and execution are separate rows in time

A single "do the thing" call would mean the decision to act and the act
itself are indistinguishable in the record, and an approval could never be
required *between* them. Splitting them is what makes human-in-the-loop
structural rather than a convention the next endpoint can forget.

## Idempotency is a database constraint, not a check

`idempotency_key` is UNIQUE. A double-clicked Confirm, a retried request and
a duplicated worker all collide on the same key and the second one loses -
enforced by the database rather than by remembering to look first. Getting
this wrong means two calendar events, and "it only happened once" is not a
property worth trusting to application code.

## Status is what the provider confirmed, never what was attempted

SUCCEEDED is written only after verification. An action whose provider call
returned but could not be verified ends UNKNOWN, which is an honest state and
deliberately not a synonym for failure - the event may well exist, and
telling someone it failed would send them to create it a second time.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Enum, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class ActionStatus(str, enum.Enum):
    PROPOSED = "proposed"  # Sentinel suggested it; nobody has been asked yet
    AWAITING_APPROVAL = "awaiting_approval"  # shown to a person, waiting
    APPROVED = "approved"  # a person said yes; not yet run
    EXECUTING = "executing"  # in flight - also the lock against double-run
    SUCCEEDED = "succeeded"  # executed AND verified
    FAILED = "failed"  # the provider refused, or verification proved absence
    # Executed, but the outcome could not be confirmed. Not the same as
    # FAILED: the change may exist, so telling the user it failed would
    # invite a duplicate.
    UNKNOWN = "unknown"
    REJECTED = "rejected"  # a person said no
    CANCELLED = "cancelled"  # withdrawn before approval


class ActionRisk(str, enum.Enum):
    # Internal to Sentinel and reversible - a reminder, a snooze. May execute
    # on a single deliberate click.
    LOW = "low"
    # Creates or changes something outside Sentinel, or something the whole
    # channel sees. Always previewed and approved.
    MEDIUM = "medium"
    # Sends something to another human, or destroys data. Always approved,
    # and nothing in this phase executes autonomously.
    HIGH = "high"


class Action(Base, UUIDPk, TimestampMixin):
    __tablename__ = "actions"
    __table_args__ = (
        # The whole duplicate-execution defence, in one constraint.
        UniqueConstraint("idempotency_key", name="uq_action_idempotency"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    # "personal:{user_id}" | "channel:{team_id}" - the same key every other
    # module uses, so an action inherits the boundary rather than restating it.
    scope_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Must match a key in the action registry. Validated server-side against
    # the allow-list; a type not in the registry cannot be proposed at all.
    action_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    risk: Mapped[ActionRisk] = mapped_column(Enum(ActionRisk, name="action_risk"), nullable=False)
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus, name="action_status"), nullable=False, default=ActionStatus.PROPOSED, index=True
    )

    # Validated parameters, after the registry's schema has accepted them.
    # Never the raw text a model produced - that is parsed and discarded.
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # What the user is shown before approving. Stored so the record proves
    # what they actually agreed to, not what the code would render today.
    preview: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Why Sentinel wants this, in plain words.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Which piece of intelligence suggested it ("commitment", "goal",
    # "situation", "attention_item"), so an action is traceable back to the
    # thing that made it seem like a good idea.
    source_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    # --- audit: who, when, and what came back
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)

    # What the provider returned, reduced to what is safe and useful: ids,
    # links, titles. Never tokens, never full response bodies.
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # How the outcome was confirmed, in words - "the event was read back from
    # the provider". An unverifiable success is not a success.
    verification: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # --- undo. Recorded rather than deleting the row: "this was done and then
    # taken back" is a different fact from "this never happened", and an audit
    # trail that quietly loses the first one is not an audit trail.
    undone_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    undone_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # What the compensator actually achieved, in plain words - including when
    # it could not fully undo the effect.
    undo_result: Mapped[str | None] = mapped_column(String(300), nullable=True)
