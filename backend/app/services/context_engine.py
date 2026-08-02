"""The Context Engine - Intelligence Core, Phase 4.

Assembles the complete, deterministic evidence package for a Situation within
its Scope. No inference, no LLM: it resolves the situation's member findings back
to full canonical Findings, gathers the Entities they concern and the provider
Evidence that backs them, and reads the situation's trajectory. The result is the
single input the Reasoning Engine consumes.

Scope-aware (reads only this scope's findings and mentions) and provider-agnostic
(works off Findings/Signals, never provider specifics), so a new provider needs
zero changes here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.context import EvidenceItem, FindingContext, SituationContext
from app.domain.finding import Finding
from app.domain.scope import Scope
from app.models.correlated_situation import Situation, SituationFinding
from app.models.entity import Entity, EntityMention
from app.services.findings import list_findings
from app.services.situation_engine import MIN_CLUSTER

# A signal kind -> provider map, so an evidence item carries its provider even
# when the finding itself is provider-agnostic (proactive situations).
_SIGNAL_PROVIDER = {
    "pr": "github", "review_submitted": "github", "commit": "github", "issue": "github",
    "email": "gmail", "calendar_event": "google_calendar", "drive_file": "google_drive",
    "channel_activity": "slack", "mention": "slack", "flagged_message": "slack",
}


def _parse(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _evidence_for(finding: Finding) -> list[EvidenceItem]:
    """The provider evidence backing one finding. Proactive findings carry
    structured evidence signals; attention findings carry their 'Open in ...'
    link - both are the leaf of the traceability chain."""
    out: list[EvidenceItem] = []
    for e in finding.evidence or []:
        if not isinstance(e, dict):
            continue
        kind = e.get("kind") or "signal"
        out.append(EvidenceItem(
            signal_id=e.get("signal_id"), kind=kind, title=e.get("title") or "",
            actor=e.get("actor"), occurred_at=_parse(e.get("occurred_at")),
            url=e.get("url"), provider=_SIGNAL_PROVIDER.get(kind),
        ))
    if not out and (finding.evidence_url or finding.provider):
        out.append(EvidenceItem(
            signal_id=None, kind=finding.kind, title=finding.title, actor=None,
            occurred_at=finding.occurred_at, url=finding.evidence_url, provider=finding.provider,
        ))
    return out


def _trajectory(situation: Situation) -> str:
    """Deterministic reading of movement from the high-water mark. No history
    table needed: below peak means it is receding; at a peak that grew past the
    minimum cluster means it built up; at the bare minimum means steady."""
    if situation.member_count < situation.peak_member_count:
        return "de-escalating"
    if situation.peak_member_count > MIN_CLUSTER:
        return "escalating"
    return "steady"


def build_context(session: Session, scope: Scope, situation: Situation, findings_by_id: dict[str, Finding] | None = None) -> SituationContext:
    """Assemble the full evidence package for one situation within its scope."""
    if findings_by_id is None:
        findings_by_id = {f.id: f for f in list_findings(session, scope)}

    members = session.execute(
        select(SituationFinding).where(SituationFinding.situation_id == situation.id)
    ).scalars().all()
    member_ids = [m.finding_id for m in members]

    # Entities each member finding concerns, gated to THIS scope's mentions.
    entities_by_finding: dict[str, dict] = {}
    all_entities: dict = {}
    if member_ids:
        rows = session.execute(
            select(EntityMention, Entity)
            .join(Entity, Entity.id == EntityMention.entity_id)
            .where(EntityMention.scope_key == scope.key, EntityMention.finding_id.in_(member_ids))
        ).all()
        for mention, entity in rows:
            entities_by_finding.setdefault(mention.finding_id, {})[entity.id] = entity
            all_entities[entity.id] = entity

    finding_ctxs: list[FindingContext] = []
    for m in members:
        f = findings_by_id.get(m.finding_id)
        if f is None:
            continue  # finding resolved/gone since correlation; skip - present ones stay fully traceable
        finding_ctxs.append(FindingContext(
            finding=f,
            entities=list(entities_by_finding.get(m.finding_id, {}).values()),
            evidence=_evidence_for(f),
        ))

    primary = session.get(Entity, situation.primary_entity_id) if situation.primary_entity_id else None
    if primary is not None:
        all_entities.setdefault(primary.id, primary)

    providers = sorted({fc.finding.provider for fc in finding_ctxs if fc.finding.provider})

    return SituationContext(
        situation=situation,
        scope_key=scope.key,
        primary_entity=primary,
        entities=list(all_entities.values()),
        findings=finding_ctxs,
        trajectory=_trajectory(situation),
        providers=providers,
    )
