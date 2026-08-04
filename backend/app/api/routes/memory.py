"""Memory API - review and manage what Sentinel has learned (Phase 6).

    GET  /memory                 what Sentinel remembers in your scope
    GET  /memory/announcements   newly learned memories, surfaced once each
    POST /memory/{id}/forget     forget a memory

Scope is derived server-side (personal), never accepted as a parameter, so one
person's memory is never read into another's - the same rule as every other
scoped surface.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.models.memory import Memory
from app.models.user import User
from app.services.investigation import personal_scope
from app.services.memory_engine import forget_memory, list_memories, pending_announcements

router = APIRouter(prefix="/memory", tags=["memory"])


def _out(m: Memory) -> dict:
    return {
        "id": str(m.id),
        "kind": m.kind.value,
        "subject_key": m.subject_key,
        "summary": m.summary,
        "strength": m.strength,
        "observation_count": m.observation_count,
        "status": m.status.value,
        "evidence": m.evidence,
        "first_observed_at": m.first_observed_at.isoformat() if m.first_observed_at else None,
        "last_observed_at": m.last_observed_at.isoformat() if m.last_observed_at else None,
    }


@router.get("")
def get_memories(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[dict]:
    scope = personal_scope(session, workspace_id, user.id)
    return [_out(m) for m in list_memories(session, scope)]


@router.get("/announcements")
def get_announcements(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Memories learned but not yet shown. Reading this MARKS them surfaced, so
    "Sentinel will remember that" appears exactly once per new memory."""
    scope = personal_scope(session, workspace_id, user.id)
    memories = pending_announcements(session, scope)
    session.commit()
    return [{"id": str(m.id), "summary": m.summary, "kind": m.kind.value} for m in memories]


@router.post("/{memory_id}/forget")
def forget(
    memory_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> dict:
    scope = personal_scope(session, workspace_id, user.id)
    mem = session.get(Memory, memory_id)
    if mem is None or mem.scope_key != scope.key:
        raise HTTPException(status_code=404, detail="Memory not found")
    forget_memory(session, memory_id)
    session.commit()
    return {"id": str(memory_id), "status": "forgotten"}
