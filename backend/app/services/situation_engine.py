"""The Situation Engine - Intelligence Core, Phase 3.

Deterministically correlates canonical Findings that share a strong Entity into
Situations. This is the integration -> intelligence leap: siloed findings become
one operational state because they resolve to the same repo / channel / service.

Rules, all deterministic and conservative:
  - Only STRONG entities (repo, channel, service) anchor a situation - a shared
    person is too weak a coincidence.
  - A situation forms when >= 2 open findings share one strong entity (via an
    ABOUT or MENTIONS link). Cross-provider is flagged, not required: two
    findings on one repo is a real situation; findings from two providers on it
    is the cross-provider synthesis we most want.
  - One situation per (scope, anchor entity): it evolves, never duplicates.
  - It auto-resolves the moment the cluster falls below two findings.
  - peak_member_count records the high-water mark - the raw material for "is
    this escalating" without any LLM.

No LLM. Titles are template-generated. Findings stay atomic and are referenced
by their stable canonical ids, so Situation -> Finding -> Signal is traceable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.finding import Finding
from app.domain.scope import Scope
from app.models.correlated_situation import Situation, SituationFinding, SituationStatus
from app.models.entity import STRONG_KINDS, Entity, EntityMention, MentionRole
from app.services.entity_engine import extract_entities
from app.services.findings import list_findings
from app.services.scope_registry import active_scopes

logger = structlog.get_logger("sentinel.situation_engine")

# The minimum cluster size for a correlation to be a situation. Two is the
# smallest number that is genuinely "more than one finding about this thing".
MIN_CLUSTER = 2

_TIER_RANK = {"critical": 0, "review": 1, "reminder": 2}


def _worst_tier(members: list[Finding]) -> str:
    return min((m.tier.value for m in members), key=lambda t: _TIER_RANK.get(t, 99))


def _title(entity: Entity | None, members: list[Finding]) -> str:
    name = (entity.display_name if entity else None) or "resource"
    n = len(members)
    providers = sorted({m.provider for m in members if m.provider})
    if len(providers) >= 2:
        return f"{name}: {n} related findings across {', '.join(providers)}"
    return f"{name}: {n} related findings"


def _upsert_situation(
    session: Session, workspace_id: uuid.UUID, scope_key: str, dedupe: str,
    entity_id: uuid.UUID, members: list[Finding], now: datetime,
) -> Situation:
    providers = {m.provider for m in members if m.provider}
    cross = len(providers) >= 2
    worst = _worst_tier(members)
    entity = session.get(Entity, entity_id)
    title = _title(entity, members)
    last_activity = max((m.occurred_at or m.created_at or now) for m in members)

    sit = session.execute(select(Situation).where(Situation.dedupe_key == dedupe)).scalar_one_or_none()
    if sit is None:
        sit = Situation(
            workspace_id=workspace_id, scope_key=scope_key, dedupe_key=dedupe,
            primary_entity_id=entity_id, status=SituationStatus.OPEN, severity=worst, title=title,
            member_count=len(members), peak_member_count=len(members),
            provider_count=len(providers) or 1, cross_provider=cross,
            first_seen_at=now, last_activity_at=last_activity, resolved_at=None,
        )
        session.add(sit)
        session.flush()
    else:
        sit.status = SituationStatus.OPEN
        sit.resolved_at = None
        sit.primary_entity_id = entity_id
        sit.severity = worst
        sit.title = title
        sit.member_count = len(members)
        sit.peak_member_count = max(sit.peak_member_count, len(members))
        sit.provider_count = len(providers) or 1
        sit.cross_provider = cross
        sit.last_activity_at = max(sit.last_activity_at, last_activity)

    # Replace the membership set - the evidence link back to atomic findings.
    session.execute(delete(SituationFinding).where(SituationFinding.situation_id == sit.id))
    for m in members:
        session.add(SituationFinding(
            situation_id=sit.id, finding_id=m.id, finding_source=m.source.value,
            tier=m.tier.value, provider=m.provider,
        ))
    return sit


def correlate(session: Session, scope: Scope, findings: list[Finding]) -> list[Situation]:
    """Form/evolve/resolve situations for one scope from its current findings.
    Assumes entity mentions are already derived (see extract_entities). Reads
    only this scope's mentions, so correlation never crosses the boundary."""
    now = datetime.now(timezone.utc)
    workspace_id = scope.workspace_id
    scope_key = scope.key
    finding_by_id = {f.id: f for f in findings}
    finding_ids = list(finding_by_id)

    mentions = session.execute(
        select(EntityMention)
        .join(Entity, Entity.id == EntityMention.entity_id)
        .where(
            EntityMention.workspace_id == workspace_id,
            EntityMention.scope_key == scope_key,
            EntityMention.finding_id.in_(finding_ids),
            Entity.kind.in_(STRONG_KINDS),
            EntityMention.role.in_([MentionRole.ABOUT, MentionRole.MENTIONS]),
        )
    ).scalars().all() if finding_ids else []

    clusters: dict[uuid.UUID, set[str]] = {}
    for m in mentions:
        clusters.setdefault(m.entity_id, set()).add(m.finding_id)

    active: set[str] = set()
    result: list[Situation] = []
    for entity_id, fids in clusters.items():
        members = [finding_by_id[fid] for fid in fids if fid in finding_by_id]
        if len(members) < MIN_CLUSTER:
            continue
        dedupe = f"{scope_key}:entity:{entity_id}"
        active.add(dedupe)
        result.append(_upsert_situation(session, workspace_id, scope_key, dedupe, entity_id, members, now))

    # Auto-resolve: any open situation in this scope whose cluster no longer
    # qualifies is deterministically over.
    open_sits = session.execute(
        select(Situation).where(Situation.scope_key == scope_key, Situation.status == SituationStatus.OPEN)
    ).scalars().all()
    for sit in open_sits:
        if sit.dedupe_key not in active:
            sit.status = SituationStatus.RESOLVED
            sit.resolved_at = now

    session.flush()
    return result


def refresh_intelligence(session: Session, scope: Scope) -> list[Situation]:
    """Run the whole Intelligence Core for ONE scope: read its findings, derive
    its entities, correlate its situations. The single scope-parametric entry
    point every future engine (Context, Reasoning, Memory, Decision) extends.
    Deterministic, no LLM."""
    findings = list_findings(session, scope)
    extract_entities(session, scope, findings)
    situations = correlate(session, scope, findings)
    # Reasoning (Phase 5) rides the same pass: it consumes the Context Engine's
    # package, never raw data, and only calls the LLM for situations that
    # changed. Local import breaks the situation<->reasoning module cycle.
    from app.services.reasoning_engine import refresh_reasoning

    refresh_reasoning(session, scope, findings)
    return situations


def refresh_intelligence_for_workspace(session: Session, workspace_id: uuid.UUID) -> list[Situation]:
    """Run the Intelligence Core for EVERY active scope in a workspace - each
    person's personal scope and each channel's scope - reusing the identical
    engines. One intelligence system, scoped, not two. Each scope is isolated so
    a failure in one never affects another; callers wrap the whole thing so an
    intelligence bug can never fail a provider sync."""
    situations: list[Situation] = []
    for scope in active_scopes(session, workspace_id):
        try:
            situations.extend(refresh_intelligence(session, scope))
        except Exception:
            logger.exception("intelligence_scope_failed", workspace_id=str(workspace_id), scope_key=scope.key)
    session.commit()
    return situations


def list_situations(session: Session, workspace_id: uuid.UUID, scope_key: str) -> list[Situation]:
    """Read the open correlated situations for a scope, worst-first."""
    rows = session.execute(
        select(Situation).where(
            Situation.workspace_id == workspace_id,
            Situation.scope_key == scope_key,
            Situation.status == SituationStatus.OPEN,
        )
    ).scalars().all()
    return sorted(rows, key=lambda s: (_TIER_RANK.get(s.severity, 99), -s.member_count, -s.last_activity_at.timestamp()))
