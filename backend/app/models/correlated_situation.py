"""The Situation Engine's object - Intelligence Core, Phase 3.

A Situation is the canonical, higher-order object of Operations Intelligence: a
coherent operational state that groups the Findings which evidence it, formed
deterministically because those findings share an Entity. This is the
integration -> intelligence leap - the three siloed findings ("we're blocked",
"PR #42 awaiting review", "deploy meeting in 20 min") become one Situation
because they resolve to one repo.

Naming: this is THE Situation of the roadmap. The legacy single-provider
proactive detector's object was renamed to ``ProactiveSituation`` (Phase 3
groundwork) to free this name - a proactive detection is really a Finding, and
a Situation is a correlation of findings.

Deterministic and provider-agnostic: the correlation is a FACT (shared entity +
scope), never a model's guess. Findings stay atomic and are only *composed*
here - a Situation references them by their stable canonical ids, so the full
chain Situation -> Finding -> Signal is preserved. No LLM: the title is
template-generated; narrative belongs to a later phase (Reasoning).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk, utcnow


class SituationStatus(str, enum.Enum):
    OPEN = "open"  # still corroborated: >= 2 open findings share the anchor entity
    RESOLVED = "resolved"  # the cluster fell below the threshold - deterministically over


class Situation(Base, UUIDPk, TimestampMixin):
    __tablename__ = "correlated_situations"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_correlated_situation_dedupe"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    # The viewer scope this situation belongs to (personal for now), mirroring
    # how findings are scoped - so one person's situations never leak to another.
    scope_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # One row per (scope, anchor entity): "{scope_key}:entity:{entity_id}".
    # This is what enforces "evolve, don't duplicate" at the DB level.
    dedupe_key: Mapped[str] = mapped_column(String(300), nullable=False)

    # The Entity that binds the findings together. Nullable only defensively;
    # every situation is created with one.
    primary_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("entities.id", ondelete="SET NULL"), nullable=True, index=True
    )

    status: Mapped[SituationStatus] = mapped_column(
        Enum(SituationStatus, name="correlated_situation_status"), nullable=False, default=SituationStatus.OPEN
    )
    # The canonical Finding tier of the worst member (critical/review/reminder),
    # so a situation is never calmer than its most serious finding.
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Trajectory, deterministically: the high-water mark of member_count. A
    # situation whose current count is below its peak is de-escalating; at its
    # peak and rising, escalating. The raw material for "is it getting worse".
    peak_member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # How many times this situation has FORMED (1 on creation, +1 each time a
    # resolved situation re-forms). The recurrence signal the Memory Engine
    # reads to learn "this keeps happening" - distinct from member_count (how
    # big it is now) and peak_member_count (how big it ever got).
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # True when the members span >= 2 providers - the cross-provider synthesis
    # that is the whole point. Single-provider clusters are still real
    # situations (3 stalled PRs on one repo), just flagged as not cross-provider.
    cross_provider: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class SituationFinding(Base, UUIDPk, TimestampMixin):
    """One canonical Finding's membership in a Situation. The evidence link that
    keeps a Situation traceable back to atomic findings and their signals."""

    __tablename__ = "situation_findings"
    __table_args__ = (UniqueConstraint("situation_id", "finding_id", name="uq_situation_finding"),)

    situation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("correlated_situations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    finding_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    finding_source: Mapped[str] = mapped_column(String(20), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
