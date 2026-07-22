"""Per-scope opt-in for actions that may run without a person present.

## What this is, honestly

A foundation, not autonomy. Nothing in Sentinel currently runs unattended;
this is the gate that a future scheduler or event-driven proposal would have
to pass, built and tested now so that adding one is a policy question rather
than an architecture change.

The default is off. A row here exists only because somebody explicitly
enabled one action type in one scope, and even then four independent
conditions must all hold before anything runs unattended
(`action_policy.autonomy_allows`):

    the action type is marked autonomy_eligible in the registry
    its effective risk is LOW
    it is REVERSIBLE - not merely compensatable
    this scope has an enabled policy row for it, created by a person

Any one of those failing means a human is asked. That is deliberately
redundant: a single flag governing whether software acts on its own is one
mistake away from acting on its own.

## Why per scope rather than per user

The unit of consent matches the unit of consequence. Enabling something in
your own context is your decision; enabling it in a channel affects everyone
in that channel, so it is a channel-admin decision and the row records who
made it.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class ActionPolicy(Base, UUIDPk, TimestampMixin):
    __tablename__ = "action_policies"
    __table_args__ = (
        UniqueConstraint("scope_key", "action_type", name="uq_action_policy_scope_type"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)

    # Explicitly enabled by a person. Disabling leaves the row so the audit
    # trail keeps who turned it on and who turned it off.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # A ceiling on unattended runs, so a loop cannot quietly execute hundreds
    # of times. Counted per day and enforced before execution.
    daily_limit: Mapped[int] = mapped_column(nullable=False, default=5)

    enabled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    enabled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
