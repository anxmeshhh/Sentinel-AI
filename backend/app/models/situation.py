"""A developing situation Sentinel noticed without being asked.

Distinct from an AttentionItem, and the distinction is the whole feature: an
AttentionItem is *one thing that arrived* ("this email is starred and
unread"). A Situation is a **reading of several signals over time** ("a
service you depend on is being withdrawn, and it has now happened").

That difference is why this has a lifecycle and AttentionItem does not:

    EMERGING  -> ACTIVE -> RESOLVED
    (first evidence)  (corroborated)  (deterministically over)

New evidence for a situation already on screen **updates that row**. It never
creates a second one - a feature that produces a fresh card every time
another related email lands is a notification generator, which is precisely
what this must not become.

`situation_key` is what makes that possible: a stable, deterministic
identifier for the underlying situation rather than for any one signal. Two
messages about the same paused project produce one key, so the second
strengthens the first instead of duplicating it.

Scoped exactly like Investigations: `scope_key` is "personal:{user_id}" or
"channel:{team_id}", and a situation is computed only from the connections
that scope authorizes. A channel situation can therefore never be assembled
out of a member's private mail.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Enum, Float, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class SituationStatus(str, enum.Enum):
    EMERGING = "emerging"  # one piece of evidence - real, but uncorroborated
    ACTIVE = "active"  # corroborated, or serious enough on its own
    RESOLVED = "resolved"  # the underlying issue is deterministically over


class SituationKind(str, enum.Enum):
    # A service or resource the user depends on is being withdrawn, paused,
    # throttled or expired. Validated against the real mailbox before it was
    # built: 5 genuine instances in 190 emails, no false positives.
    SERVICE_JEOPARDY = "service_jeopardy"
    # A meeting is imminent and something it depends on is still unresolved.
    MEETING_UNPREPARED = "meeting_unprepared"
    # A resource a human marked CRITICAL has gone quiet - had activity, then
    # stopped past a threshold. Provider-agnostic: a repository that stopped
    # committing, a channel that went silent, a project that stopped moving all
    # look the same to the engine. Only CRITICAL resources qualify: the
    # classification is the context that makes silence meaningful rather than
    # noise (see models/connection.py ResourcePriority).
    RESOURCE_STALLED = "resource_stalled"


class Situation(Base, UUIDPk, TimestampMixin):
    __tablename__ = "situations"
    __table_args__ = (
        # One row per underlying situation per scope. This constraint is what
        # enforces "evolve, don't duplicate" at the database level rather
        # than trusting the detector to behave.
        UniqueConstraint("scope_key", "situation_key", name="uq_situation_scope_key"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    situation_key: Mapped[str] = mapped_column(String(300), nullable=False)

    kind: Mapped[SituationKind] = mapped_column(Enum(SituationKind, name="situation_kind"), nullable=False)
    status: Mapped[SituationStatus] = mapped_column(
        Enum(SituationStatus, name="situation_status"), nullable=False, default=SituationStatus.EMERGING
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # --- FACT: what was deterministically observed. Never model-written.
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_count: Mapped[int] = mapped_column(nullable=False, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_evidence_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Deterministic, not model-assigned: importance decides whether this is
    # worth a person's attention at all, so it must not be something the
    # model can talk itself into.
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    # --- INFERENCE + RECOMMENDATION: the model's reading of the evidence
    # above. Empty until the situation earns an LLM call.
    what_is_developing: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_it_matters: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_next_steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    llm_calls: Mapped[int] = mapped_column(nullable=False, default=0)
    # Bumped whenever the evidence set materially changes; the narrative is
    # only re-synthesized when it does, so a re-run costs zero tokens.
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
