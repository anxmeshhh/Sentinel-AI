"""The Entity Engine - Intelligence Core, Phase 2.

Deterministically derives the canonical Entities a Finding concerns, and records
them as EntityMentions. No LLM, no guessing: entities come from structured
provenance (the finding's connection, its evidence signals, a proactive
detection's key), plus one conservative text bridge (a known strong entity's
name appearing as a whole word in another finding's text) - which is what lets a
Slack blocker about "api" line up with the GitHub repo `api` in the next phase.

Idempotent: mentions are re-derived every refresh and reconciled against what is
stored, so a re-run never duplicates and a finding that changed what it concerns
has its stale mentions pruned.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.finding import Finding, FindingSource
from app.domain.scope import Scope
from app.models.connection import Connection, Provider
from app.models.entity import STRONG_KINDS, Entity, EntityKind, EntityMention, MentionRole
from app.models.signal import Signal

# A short name must be at least this long to be matched in free text - shorter
# tokens ("api" is 3) collide with common words too easily. Deliberately
# conservative: a missed correlation is cheaper than a false one.
_MIN_TEXT_MATCH_LEN = 4


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except (ValueError, TypeError):
        return None


def _resource_entity_for_connection(conn: Connection | None) -> tuple[EntityKind, str, str] | None:
    """The one resource a connection represents, canonicalized. None for personal
    Google surfaces - a mailbox or calendar is not a shared operational entity."""
    if conn is None:
        return None
    if conn.provider == Provider.GITHUB and conn.org and conn.repo:
        return (EntityKind.REPO, f"github:{conn.org}/{conn.repo}", conn.repo)
    if conn.provider == Provider.SLACK and conn.repo:
        return (EntityKind.CHANNEL, f"slack:{conn.repo}", conn.display_name or conn.full_name)
    # Microsoft Teams: a monitored channel is a CHANNEL entity exactly like a
    # Slack one. This single line is the whole of Teams' correlation support -
    # everything above it (situations, context, reasoning, memory, decisions)
    # already works on entities and never learns that Teams exists. The channel
    # id is globally unique in Graph, so it alone canonicalizes the entity.
    if conn.provider == Provider.MICROSOFT_TEAMS and conn.repo:
        return (EntityKind.CHANNEL, f"msteams:{conn.repo}", conn.display_name or conn.full_name)
    return None


def _structured_mentions(session: Session, finding: Finding) -> list[tuple[EntityKind, str, str, MentionRole, float]]:
    """(kind, key, display_name, role, confidence) from a finding's structured
    provenance. Deterministic - reads connections and evidence signals only."""
    out: list[tuple[EntityKind, str, str, MentionRole, float]] = []
    connection_ids: set[uuid.UUID] = set()

    # Attention findings carry their source connection directly.
    if finding.connection_id is not None:
        connection_ids.add(finding.connection_id)

    # Proactive findings carry evidence signals (each points at a connection and
    # an actor), and a service-jeopardy encodes the service in its key.
    if finding.source is FindingSource.PROACTIVE and finding.raw is not None:
        sit = finding.raw
        kind_value = getattr(getattr(sit, "kind", None), "value", None)
        if kind_value == "service_jeopardy" and getattr(sit, "situation_key", None):
            suffix = sit.situation_key.split(":", 1)[1] if ":" in sit.situation_key else sit.situation_key
            name = (suffix.split(":")[-1] or suffix).strip()
            if name:
                out.append((EntityKind.SERVICE, f"service:{name.lower()}", name, MentionRole.ABOUT, 1.0))
        for ev in finding.evidence or []:
            sid = _uuid_or_none(ev.get("signal_id") if isinstance(ev, dict) else None)
            sig = session.get(Signal, sid) if sid else None
            if sig is None:
                continue
            connection_ids.add(sig.connection_id)
            actor = (sig.actor or "").strip()
            if actor:
                out.append((EntityKind.PERSON, f"person:{actor.lower()}", actor, MentionRole.ACTOR, 1.0))

    for cid in connection_ids:
        res = _resource_entity_for_connection(session.get(Connection, cid))
        if res is not None:
            out.append((res[0], res[1], res[2], MentionRole.ABOUT, 1.0))
    return out


def _short_name(entity: Entity) -> str:
    return (entity.display_name or "").lstrip("#").strip()


def _text_mentions(finding: Finding, strong_entities: list[Entity]) -> list[tuple[uuid.UUID, MentionRole, float]]:
    """MENTIONS links: a strong entity's short name appearing as a whole word in
    the finding's text. The conservative cross-provider bridge."""
    text = f"{finding.title or ''} {finding.summary or ''}".lower()
    out: list[tuple[uuid.UUID, MentionRole, float]] = []
    for ent in strong_entities:
        name = _short_name(ent).lower()
        if len(name) < _MIN_TEXT_MATCH_LEN:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", text):
            out.append((ent.id, MentionRole.MENTIONS, 0.6))
    return out


def _upsert_entity(session: Session, workspace_id: uuid.UUID, kind: EntityKind, key: str, name: str, now: datetime) -> Entity:
    ent = session.execute(
        select(Entity).where(Entity.workspace_id == workspace_id, Entity.kind == kind, Entity.key == key)
    ).scalar_one_or_none()
    if ent is None:
        ent = Entity(workspace_id=workspace_id, kind=kind, key=key, display_name=name or key, first_seen_at=now, last_seen_at=now)
        session.add(ent)
        session.flush()
    else:
        ent.last_seen_at = now
        if name and not ent.display_name:
            ent.display_name = name
    return ent


def extract_entities(session: Session, scope: Scope, findings: list[Finding]) -> None:
    """Derive and reconcile a scope's entity mentions. Two passes: structured
    provenance first (so entities exist), then a text bridge against the
    now-known strong entities.

    Entities themselves are workspace-level and scope-NEUTRAL (a repo is one
    repo); the scope lives on the mention (the edge), so reconciliation only
    ever touches this scope's mentions and one scope can never disturb another."""
    now = datetime.now(timezone.utc)
    workspace_id = scope.workspace_id
    scope_key = scope.key

    # desired[finding_id][(entity_id, role)] = (finding_source, confidence)
    desired: dict[str, dict[tuple[uuid.UUID, MentionRole], tuple[str, float]]] = {}

    # PASS 1 - structured entities and their ABOUT/ACTOR mentions.
    for f in findings:
        for kind, key, name, role, conf in _structured_mentions(session, f):
            ent = _upsert_entity(session, workspace_id, kind, key, name, now)
            desired.setdefault(f.id, {})[(ent.id, role)] = (f.source.value, conf)
    session.flush()

    # PASS 2 - text bridge against known strong entities, skipping anything the
    # finding is already ABOUT (a MENTIONS on top of ABOUT adds nothing).
    strong = session.execute(
        select(Entity).where(Entity.workspace_id == workspace_id, Entity.kind.in_(STRONG_KINDS))
    ).scalars().all()
    for f in findings:
        about_ids = {eid for (eid, role) in desired.get(f.id, {}) if role is MentionRole.ABOUT}
        for eid, role, conf in _text_mentions(f, strong):
            if eid in about_ids:
                continue
            desired.setdefault(f.id, {}).setdefault((eid, role), (f.source.value, conf))

    # Reconcile against stored mentions for exactly these findings IN THIS SCOPE,
    # so a channel run never prunes or reads a personal run's mentions.
    finding_ids = [f.id for f in findings]
    existing = session.execute(
        select(EntityMention).where(
            EntityMention.workspace_id == workspace_id,
            EntityMention.scope_key == scope_key,
            EntityMention.finding_id.in_(finding_ids),
        )
    ).scalars().all() if finding_ids else []
    existing_by_key = {(m.finding_id, m.entity_id, m.role): m for m in existing}

    desired_keys: set[tuple[str, uuid.UUID, MentionRole]] = set()
    for fid, entries in desired.items():
        for (eid, role), (src, conf) in entries.items():
            desired_keys.add((fid, eid, role))
            if (fid, eid, role) not in existing_by_key:
                session.add(EntityMention(
                    workspace_id=workspace_id, scope_key=scope_key, entity_id=eid, finding_id=fid,
                    finding_source=src, role=role, confidence=conf,
                ))
    for key, mention in existing_by_key.items():
        if key not in desired_keys:
            session.delete(mention)

    # Prune ORPHANS: mentions whose finding no longer exists at all.
    #
    # The reconciliation above only covers findings passed in on this run, so a
    # mention survived indefinitely once its finding vanished entirely (a
    # resolved situation, a dismissed item). Measured on real data: an entity
    # showed 2 mentions while only 1 live finding referenced it, which
    # overstates how close that entity is to correlating. Correlation itself was
    # never fooled - it intersects with live findings - but the stored state was
    # wrong, and wrong state eventually becomes a wrong decision.
    live_ids = set(finding_ids)
    for mention in session.execute(
        select(EntityMention).where(
            EntityMention.workspace_id == workspace_id,
            EntityMention.scope_key == scope_key,
        )
    ).scalars().all():
        if mention.finding_id not in live_ids:
            session.delete(mention)

    session.flush()
