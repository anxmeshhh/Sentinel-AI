"""The Memory Engine's object - Intelligence Core, Phase 6.

A Memory is durable, meaningful operational knowledge Sentinel has LEARNED - not
a raw event. It is created only when a deterministic pattern crosses a
meaningfulness threshold (v1: a situation that has recurred), reinforced as the
pattern repeats, and eventually forgotten if it goes quiet. Every memory is:

  - explainable - a deterministic ``summary`` plus ``evidence`` (the occurrences
    that produced it); no LLM writes a memory, so it can never be a hallucination;
  - traceable   - ``subject_key`` points at the thing it is about (a situation's
    dedupe_key), which resolves back through Situation -> Finding -> Signal;
  - scoped      - Personal and Workspace memory are separated by ``scope_key``,
    the same seam as everything else, so a person's learning never leaks to a
    channel;
  - reviewable  - listed and forgettable through the memory API.

``announced_at`` is the surfacing queue: NULL means "learned but not yet shown",
so the product can raise "Sentinel will remember that" exactly once per new
memory - never on reinforcement, never on a plain sync.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Enum, Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk, utcnow


class MemoryKind(str, enum.Enum):
    # A correlated situation that has formed, resolved and formed again - the
    # flagship "this keeps happening". The model is intentionally extensible:
    # SALIENT_ENTITY, PRIORITY_PREFERENCE, RESOLUTION_PATTERN slot in later
    # without a schema change to the shape below.
    RECURRING_SITUATION = "recurring_situation"


class MemoryStatus(str, enum.Enum):
    ACTIVE = "active"
    FORGOTTEN = "forgotten"


class Memory(Base, UUIDPk, TimestampMixin):
    __tablename__ = "memories"
    __table_args__ = (UniqueConstraint("scope_key", "kind", "subject_key", name="uq_memory_scope_kind_subject"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    kind: Mapped[MemoryKind] = mapped_column(Enum(MemoryKind, name="memory_kind"), nullable=False)
    # What the memory is about - a situation's dedupe_key for RECURRING_SITUATION.
    subject_key: Mapped[str] = mapped_column(String(300), nullable=False)

    summary: Mapped[str] = mapped_column(String(500), nullable=False)  # deterministic, human-readable
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)  # 0..1, grows with observations
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    status: Mapped[MemoryStatus] = mapped_column(Enum(MemoryStatus, name="memory_status"), nullable=False, default=MemoryStatus.ACTIVE)

    # The occurrences/references that justify this memory - the explainability trail.
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    first_observed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_observed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    # NULL until the product has shown "Sentinel will remember that" for it.
    announced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    forgotten_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
