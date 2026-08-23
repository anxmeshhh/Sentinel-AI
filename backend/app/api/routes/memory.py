"""Memory API - review and manage what Sentinel has learned (Phase 6).

    GET  /memory                 what Sentinel remembers in your scope
    GET  /memory/announcements   newly learned memories, surfaced once each
    POST /memory/{id}/forget     forget a memory

    GET  /teams/{id}/memory      what Sentinel remembers for one channel

Scope is derived server-side, never accepted as a parameter, so one person's
memory is never read into another's - the same rule as every other scoped
surface. The channel read takes its scope from the channel and gates on
membership, so the Individual -> never -> Collective boundary is unchanged.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id, require_channel_role
from app.models.memory import Memory
from app.models.team import ChannelRole
from app.models.user import User
from app.services.investigation import channel_scope, personal_scope
from app.services.memory_engine import forget_memory, list_memories, pending_announcements

router = APIRouter(prefix="/memory", tags=["memory"])

# Channel-scoped read on a second, un-prefixed router - its path is /teams/...,
# not /memory/... Same shape goals.py uses; both are registered in main.py.
channel_router = APIRouter(tags=["memory"])

_ANY_MEMBER = [ChannelRole.CHANNEL_ADMIN, ChannelRole.CHANNEL_MEMBER]


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


@channel_router.get("/teams/{team_id}/memory")
def get_channel_memories(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """What Sentinel has learned about this channel.

    The Memory Engine already writes these: refresh_memory runs for every
    active scope on each sync, channels included - there was simply no route
    to read a channel's, so the rows existed and were unreachable. This adds
    the read and nothing else: no new recurrence rule, no new decay, no new
    threshold. Forgetting stays personal-only on purpose - a channel memory is
    shared state, and who may retire it is a separate decision from who may
    read it.
    """
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    return [_out(m) for m in list_memories(session, channel_scope(session, team_id))]


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
