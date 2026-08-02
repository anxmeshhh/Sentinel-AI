"""The canonical Finding read - the single entry point every layer above the
detectors uses instead of touching attention_items or situations directly.

Intelligence Core, Phase 1. This maps the two deterministic pipelines onto the
one canonical Finding (see app/domain/finding.py). It reuses the existing
scoped readers verbatim - ``list_attention`` and ``list_situations`` - so scope
and authorization are identical to the surfaces that already display these
(Attention's "Now" and "Risks"). It introduces no new query, no new state, and
no LLM: it is a pure re-projection.

The tier mapping here is the *single* definition of critical/review/reminder.
The verdict used to compute this inline in two places (attention priority and
situation importance); now both flow through here so they cannot drift.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.domain.finding import Finding, FindingSource, FindingStatus, FindingTier
from app.domain.scope import Scope, ScopeType
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState
from app.models.situation import ProactiveSituation, ProactiveKind, ProactiveStatus
from app.services.attention_engine import list_attention
from app.services.proactive import list_situations

_ATTENTION_STATUS = {
    AttentionState.NEW: FindingStatus.OPEN,
    AttentionState.DONE: FindingStatus.RESOLVED,
    AttentionState.SNOOZED: FindingStatus.SNOOZED,
    AttentionState.DISMISSED: FindingStatus.DISMISSED,
}
_SITUATION_STATUS = {
    ProactiveStatus.EMERGING: FindingStatus.OPEN,
    ProactiveStatus.ACTIVE: FindingStatus.OPEN,
    ProactiveStatus.RESOLVED: FindingStatus.RESOLVED,
}


def _attention_tier(item: AttentionItem) -> FindingTier:
    # 0.8 is the same cutoff the finding card uses for its red "Critical" dot.
    if item.origin is AttentionOrigin.MANUAL:
        return FindingTier.REMINDER
    return FindingTier.CRITICAL if item.priority >= 0.8 else FindingTier.REVIEW


def _situation_tier(sit: ProactiveSituation) -> FindingTier:
    # Mirrors the former attention.py::_situation_is_critical exactly: a stalled
    # resource is never an emergency however long it has been quiet - it is
    # always "review"; other situations become critical only at the very top of
    # the importance scale (a service torn down, not merely paused).
    critical = sit.importance >= 0.9 and sit.kind is not ProactiveKind.RESOURCE_STALLED
    return FindingTier.CRITICAL if critical else FindingTier.REVIEW


def _from_attention(item: AttentionItem) -> Finding:
    return Finding(
        id=f"attention:{item.id}",
        source=FindingSource.ATTENTION,
        source_id=item.id,
        kind=item.type.value,
        title=item.title,
        summary=item.why,
        severity=item.priority,
        tier=_attention_tier(item),
        status=_ATTENTION_STATUS.get(item.state, FindingStatus.OPEN),
        provider=item.source_provider,
        connection_id=item.connection_id,
        confidence=None,
        evidence_url=item.evidence_url,
        evidence=[],
        narrative=None,
        occurred_at=item.due_at,
        created_at=item.created_at,
        raw=item,
    )


def _from_situation(sit: ProactiveSituation) -> Finding:
    return Finding(
        id=f"situation:{sit.id}",
        source=FindingSource.PROACTIVE,
        source_id=sit.id,
        kind=sit.kind.value,
        title=sit.title,
        summary=sit.why_it_matters or sit.title,
        severity=sit.importance,
        tier=_situation_tier(sit),
        status=_SITUATION_STATUS.get(sit.status, FindingStatus.OPEN),
        provider=None,  # situations are provider-agnostic; the Entity Layer (Phase 2) supplies this
        connection_id=None,
        confidence=sit.confidence,
        evidence_url=None,
        evidence=list(sit.evidence or []),
        narrative=sit.what_is_developing,
        occurred_at=sit.last_evidence_at,
        created_at=sit.created_at,
        raw=sit,
    )


def _attention_in_scope(session: Session, scope: Scope) -> list[AttentionItem]:
    """The attention items visible in a scope, gated on ``connection_ids``.

    For a personal scope this reproduces ``list_attention(viewer_user_id=...)``
    exactly - its connection set IS the viewer's connections, plus the viewer's
    own manual reminders. For a channel scope it is the detected items whose
    connection the channel is authorized for; manual reminders belong to a
    person, never a channel (the same rule the channel briefing enforces).
    """
    items = list_attention(session, scope.workspace_id)
    if scope.type is ScopeType.PERSONAL:
        return [
            i for i in items
            if (i.origin is AttentionOrigin.MANUAL and i.created_by_user_id == scope.owner_id)
            or (i.origin is AttentionOrigin.DETECTED and i.connection_id in scope.connection_ids)
        ]
    return [i for i in items if i.origin is AttentionOrigin.DETECTED and i.connection_id in scope.connection_ids]


def list_findings(session: Session, scope: Scope) -> list[Finding]:
    """Every open canonical finding for one scope, unified from both pipelines.

    The single Scope-based reader every Intelligence Core engine uses. Personal
    and channel scopes flow through the identical path - only the visible
    connection set differs - so there is one intelligence system, not two.
    Ordered critical-first, then by raw severity, so the highest-signal leads.
    """
    items = _attention_in_scope(session, scope)
    situations = list_situations(session, scope)

    findings = [_from_attention(i) for i in items] + [_from_situation(s) for s in situations]
    _TIER_RANK = {FindingTier.CRITICAL: 0, FindingTier.REVIEW: 1, FindingTier.REMINDER: 2}
    findings.sort(key=lambda f: (_TIER_RANK[f.tier], -f.severity))
    return findings
