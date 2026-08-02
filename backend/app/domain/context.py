"""The Context Engine's output - Intelligence Core, Phase 4.

A SituationContext is the complete, bounded, deterministic evidence package for
one Situation, assembled within its Scope: the member Findings resolved back to
full canonical objects, the Entities they concern, and the provider Evidence
that backs them - plus the situation's own trajectory. Nothing is inferred here;
it is pure gathering and structuring.

This is the SINGLE input the Reasoning Engine (Phase 5) is allowed to see. The
LLM never touches raw provider data - only ``to_facts()``, a small dict of
already-concluded facts. That structural choice is what makes "the LLM is never
the source of truth" true by construction rather than by prompt-begging.

Assembled on demand (no table), like Prepare Me, so it is always fresh and
carries the full traceability chain: Context -> Situation -> Finding -> Signal
-> provider evidence url.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.finding import Finding
from app.models.correlated_situation import Situation
from app.models.entity import Entity


@dataclass
class EvidenceItem:
    """One piece of provider evidence backing a finding - a signal or a link.
    The leaf of the traceability chain (its ``url``/``signal_id`` points at the
    real provider artifact)."""

    signal_id: str | None
    kind: str
    title: str
    actor: str | None
    occurred_at: datetime | None
    url: str | None
    provider: str | None


@dataclass
class FindingContext:
    """One member finding, with the entities it concerns and its evidence."""

    finding: Finding
    entities: list[Entity] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)


@dataclass
class SituationContext:
    situation: Situation
    scope_key: str
    primary_entity: Entity | None
    entities: list[Entity]
    findings: list[FindingContext]
    trajectory: str  # "escalating" | "steady" | "de-escalating" - deterministic, from peak vs current
    providers: list[str]

    def fingerprint(self) -> str:
        """A deterministic hash of the material facts. The Reasoning Engine only
        re-runs (and only spends an LLM call) when this changes - so a stable
        situation costs zero tokens no matter how often intelligence refreshes."""
        parts = [
            self.situation.severity,
            str(self.situation.member_count),
            str(self.situation.cross_provider),
            self.trajectory,
        ]
        parts += sorted(f"{fc.finding.id}:{fc.finding.tier.value}" for fc in self.findings)
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:64]

    def to_facts(self) -> dict[str, Any]:
        """The ONLY thing the LLM is given: already-concluded facts, bounded and
        provider-agnostic. No raw email bodies or message text beyond a finding's
        own title - the LLM explains conclusions, it does not re-derive them."""
        return {
            "situation": self.situation.title,
            "severity": self.situation.severity,
            "cross_provider": self.situation.cross_provider,
            "trajectory": self.trajectory,
            "anchor": self.primary_entity.display_name if self.primary_entity else None,
            "findings": [
                {
                    "what": fc.finding.title,
                    "kind": fc.finding.kind,
                    "severity": fc.finding.tier.value,
                    "provider": fc.finding.provider,
                    "evidence": [
                        {"what": e.title, "when": e.occurred_at.isoformat() if e.occurred_at else None, "url": e.url}
                        for e in fc.evidence[:3]
                    ],
                }
                for fc in self.findings[:10]
            ],
        }
