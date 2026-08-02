"""The canonical Finding - the single deterministic source of truth for
"something an operator should know about".

Intelligence Core, Phase 1. Today, findings live in two deterministic
pipelines with different shapes: attention_items (discrete "look at this")
and situations (an ongoing operational state, optionally with an LLM
narrative). Everything above the detectors had to know about both. This object
unifies them behind one shape so the layers to come - the Entity Layer
(Phase 2, which tags findings with the entities they concern) and the Situation
Engine (Phase 3, which correlates findings across providers) - reason over one
kind of thing.

This is deliberately a *read model*. It has no table of its own: it is mapped
from the existing rows by services/findings.py. The detectors and their storage
are unchanged, so no provider can break and no data migrates. When a later
phase needs findings to carry their own persistent state (e.g. entity tags),
that state attaches by the stable ``Finding.id`` rather than by widening the
source tables.

NOT to be confused with app.models.finding.AgentFinding, which is one LLM
agent's opinion within a run - a different, model-produced concept.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class FindingSource(str, enum.Enum):
    """Which deterministic pipeline produced the finding. Provenance only -
    transitional, since a later phase may unify the pipelines physically. The
    layers above should branch on ``kind``/``tier``, not on source."""

    ATTENTION = "attention"  # attention_items - a discrete "look at this"
    PROACTIVE = "proactive"  # situations - an ongoing operational state


class FindingTier(str, enum.Enum):
    """The single severity ladder the whole app agrees on. Replaces the two
    parallel notions - attention ``priority >= 0.8`` and situation
    ``importance >= 0.9`` - with one vocabulary, computed once (see
    services/findings.py) so a card and the verdict can never disagree on what
    "critical" means."""

    CRITICAL = "critical"
    REVIEW = "review"
    REMINDER = "reminder"  # a person-created manual reminder, not a detection


class FindingStatus(str, enum.Enum):
    """Normalized lifecycle across both pipelines. Maps AttentionState
    (new/done/snoozed/dismissed) and SituationStatus (emerging/active/resolved)
    onto one ladder: OPEN still needs a person, RESOLVED is deterministically
    over, DISMISSED was waved off, SNOOZED is deferred."""

    OPEN = "open"
    SNOOZED = "snoozed"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


@dataclass(frozen=True)
class Finding:
    """One deterministic finding, provider-agnostic.

    ``id`` is stable and source-prefixed ("attention:<uuid>" / "situation:<uuid>")
    so later phases can reference a finding without caring which table it came
    from. ``severity`` is the raw 0..1 score from the source (attention priority
    or situation importance); ``tier`` is the app-wide bucketing of it.
    """

    id: str
    source: FindingSource
    source_id: uuid.UUID
    kind: str  # detector type: "stale_pr", "resource_stalled", "slack_blocker", ...
    title: str
    summary: str
    severity: float  # 0..1
    tier: FindingTier
    status: FindingStatus
    provider: str | None = None
    connection_id: uuid.UUID | None = None
    confidence: float | None = None  # situations carry one; attention items do not
    evidence_url: str | None = None
    evidence: list[Any] = field(default_factory=list)
    # The situation's LLM narrative if it earned one; None for attention items
    # and un-synthesized situations. Preserved, not produced here - Phase 1
    # introduces no new LLM calls.
    narrative: str | None = None
    occurred_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Transitional escape hatch: the underlying ORM row, so a caller still mid-
    # migration (e.g. the verdict's deterministic summary phrasing) can reach a
    # field not yet lifted onto this object. Phase 2+ code should prefer the
    # canonical fields above and leave this alone.
    raw: Any = None

    @property
    def is_reminder(self) -> bool:
        return self.tier is FindingTier.REMINDER

    @property
    def is_critical(self) -> bool:
        return self.tier is FindingTier.CRITICAL
