"""The Memory Engine - Intelligence Core, Phase 6.

Learns durable, meaningful operational knowledge from the deterministic layers -
never from raw events, never from an LLM. v1 learns one thing well: a correlated
situation that has RECURRED (formed, resolved, formed again). When that crosses
the threshold a Memory is created; as it recurs the memory is reinforced; if it
goes quiet for a long time it is forgotten. Everything is a deterministic
function of ``Situation.occurrence_count``, so every memory is explainable and
reviewable.

Scope-aware throughout (a memory belongs to the scope that learned it), so
Personal and Workspace memory never mix.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.scope import Scope
from app.models.correlated_situation import Situation
from app.models.memory import Memory, MemoryKind, MemoryStatus

# A situation must have formed at least twice (once is not a pattern) before it
# is worth remembering. Deliberately conservative - a memory is a promise.
RECURRENCE_THRESHOLD = 2
# Long-term by design: a learned pattern is only forgotten after a long silence.
FORGET_AFTER = timedelta(days=120)


def _strength(occurrence_count: int) -> float:
    return round(min(1.0, 0.4 + 0.2 * (occurrence_count - 1)), 2)


def _summary(situation: Situation) -> str:
    return f"“{situation.title}” keeps recurring — seen {situation.occurrence_count} times."


def _evidence(situation: Situation) -> dict:
    return {
        "situation_id": str(situation.id),
        "dedupe_key": situation.dedupe_key,
        "occurrence_count": situation.occurrence_count,
        "title": situation.title,
        "severity": situation.severity,
    }


def _upsert_recurring(session: Session, scope: Scope, situation: Situation, now: datetime) -> tuple[Memory, bool]:
    mem = session.execute(
        select(Memory).where(
            Memory.scope_key == scope.key,
            Memory.kind == MemoryKind.RECURRING_SITUATION,
            Memory.subject_key == situation.dedupe_key,
        )
    ).scalar_one_or_none()

    if mem is None:
        mem = Memory(
            workspace_id=situation.workspace_id, scope_key=scope.key, kind=MemoryKind.RECURRING_SITUATION,
            subject_key=situation.dedupe_key, summary=_summary(situation), strength=_strength(situation.occurrence_count),
            observation_count=1, status=MemoryStatus.ACTIVE, evidence=_evidence(situation),
            first_observed_at=now, last_observed_at=now, announced_at=None,
        )
        session.add(mem)
        session.flush()
        return mem, True

    # Reinforce only on a genuinely new occurrence, so a plain sync never bumps it.
    prev = mem.evidence.get("occurrence_count", 0) if isinstance(mem.evidence, dict) else 0
    if situation.occurrence_count > prev:
        mem.observation_count += 1
        mem.strength = _strength(situation.occurrence_count)
        mem.summary = _summary(situation)
        mem.evidence = _evidence(situation)
        mem.last_observed_at = now
        if mem.status is MemoryStatus.FORGOTTEN:  # it came back - revive it
            mem.status = MemoryStatus.ACTIVE
            mem.forgotten_at = None
    return mem, False


def _decay(session: Session, scope: Scope, now: datetime) -> None:
    stale = session.execute(
        select(Memory).where(
            Memory.scope_key == scope.key,
            Memory.status == MemoryStatus.ACTIVE,
            Memory.last_observed_at < now - FORGET_AFTER,
        )
    ).scalars().all()
    for m in stale:
        m.status = MemoryStatus.FORGOTTEN
        m.forgotten_at = now


def refresh_memory(session: Session, scope: Scope) -> list[Memory]:
    """Observe the scope's recurring situations and learn/reinforce/forget.
    Returns only the NEWLY created memories (what the product may announce)."""
    now = datetime.now(timezone.utc)
    situations = session.execute(
        select(Situation).where(
            Situation.scope_key == scope.key,
            Situation.occurrence_count >= RECURRENCE_THRESHOLD,
        )
    ).scalars().all()

    newly: list[Memory] = []
    for sit in situations:
        _, created = _upsert_recurring(session, scope, sit, now)
        if created:
            newly.append(_)
    _decay(session, scope, now)
    session.flush()
    return newly


def matching_memory(session: Session, scope: Scope, situation: Situation) -> Memory | None:
    """The active memory (if any) about this situation - what the Decision Engine
    reads to boost priority transparently."""
    return session.execute(
        select(Memory).where(
            Memory.scope_key == scope.key,
            Memory.status == MemoryStatus.ACTIVE,
            Memory.subject_key == situation.dedupe_key,
        )
    ).scalar_one_or_none()


def list_memories(session: Session, scope: Scope, *, include_forgotten: bool = False) -> list[Memory]:
    stmt = select(Memory).where(Memory.scope_key == scope.key)
    if not include_forgotten:
        stmt = stmt.where(Memory.status == MemoryStatus.ACTIVE)
    rows = session.execute(stmt).scalars().all()
    return sorted(rows, key=lambda m: -m.strength)


def pending_announcements(session: Session, scope: Scope) -> list[Memory]:
    """Active memories not yet surfaced. Reading them MARKS them announced, so
    "Sentinel will remember that" shows exactly once per new memory."""
    rows = session.execute(
        select(Memory).where(
            Memory.scope_key == scope.key,
            Memory.status == MemoryStatus.ACTIVE,
            Memory.announced_at.is_(None),
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for m in rows:
        m.announced_at = now
    session.flush()
    return rows


def forget_memory(session: Session, memory_id: uuid.UUID) -> Memory | None:
    """User management: forget a memory. It stays as a FORGOTTEN record (auditable),
    it is not hard-deleted."""
    mem = session.get(Memory, memory_id)
    if mem is None:
        return None
    mem.status = MemoryStatus.FORGOTTEN
    mem.forgotten_at = datetime.now(timezone.utc)
    session.flush()
    return mem
