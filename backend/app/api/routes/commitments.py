"""Commitment Intelligence routes.

Two scopes, same shape as Proactive and Investigate: the scope is derived
server-side, never accepted from the caller, because it decides both what may
be read and where a new commitment lands.

    GET    /commitments                     your own (private)
    POST   /commitments                     state one privately
    GET    /teams/{id}/commitments          the channel's (shared)
    POST   /teams/{id}/commitments          state one for the channel

    POST   /commitments/{id}/resolve|dismiss|reopen

Mutations are guarded by the commitment's own `scope_key`: a channel
commitment can only be acted on by a member of that channel, and a personal
one only by its owner - checked from the record rather than from the path, so
there is one rule instead of two.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id, require_channel_role
from app.models.commitment import Commitment
from app.models.team import ChannelRole, Team
from app.models.user import User
from app.schemas.commitment import CommitmentCreate, CommitmentOut, CommitmentResolve
from app.services.commitments import (
    create_manual_commitment,
    dismiss_commitment,
    list_commitments,
    refresh_commitments,
    reopen_commitment,
    resolve_commitment,
)
from app.services.investigation import channel_scope, personal_scope

router = APIRouter(tags=["commitments"])

_ANY_MEMBER = [ChannelRole.CHANNEL_ADMIN, ChannelRole.CHANNEL_MEMBER]


# --- individual ------------------------------------------------------------


@router.get("/commitments", response_model=list[CommitmentOut])
def my_commitments(
    refresh: bool = False,
    include_closed: bool = False,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[CommitmentOut]:
    scope = personal_scope(session, workspace_id, user.id)
    if refresh:
        return refresh_commitments(session, workspace_id, scope)
    return list_commitments(session, scope, include_closed=include_closed)


@router.post("/commitments", response_model=CommitmentOut, status_code=201)
def add_my_commitment(
    payload: CommitmentCreate,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> CommitmentOut:
    """Private by construction - it lands in the caller's own scope, which no
    channel query ever reads."""
    return create_manual_commitment(
        session,
        workspace_id=workspace_id,
        scope=personal_scope(session, workspace_id, user.id),
        what=payload.what,
        due_at=payload.due_at,
        owner_label=payload.owner_label,
        user_id=user.id,
    )


# --- channel ---------------------------------------------------------------


@router.get("/teams/{team_id}/commitments", response_model=list[CommitmentOut])
def channel_commitments(
    team_id: uuid.UUID,
    refresh: bool = False,
    include_closed: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CommitmentOut]:
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    team = session.get(Team, team_id)
    scope = channel_scope(session, team_id)
    if refresh:
        return refresh_commitments(session, team.workspace_id, scope)
    return list_commitments(session, scope, include_closed=include_closed)


@router.post("/teams/{team_id}/commitments", response_model=CommitmentOut, status_code=201)
def add_channel_commitment(
    team_id: uuid.UUID,
    payload: CommitmentCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommitmentOut:
    """A commitment the whole channel can see. Any member may state one -
    recording what the team agreed is not an administrative act."""
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    team = session.get(Team, team_id)
    return create_manual_commitment(
        session,
        workspace_id=team.workspace_id,
        scope=channel_scope(session, team_id),
        what=payload.what,
        due_at=payload.due_at,
        owner_label=payload.owner_label,
        user_id=user.id,
    )


# --- lifecycle actions -----------------------------------------------------


def _authorized(session: Session, commitment_id: uuid.UUID, user: User) -> Commitment:
    """One authorization rule for every mutation, read off the record itself.

    A personal commitment belongs to exactly one person; a channel one to
    that channel's members. Deriving this from `scope_key` rather than from
    the URL means a new action route cannot accidentally ship without a check.
    """
    commitment = session.get(Commitment, commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Not found")

    kind, _, owner_id = commitment.scope_key.partition(":")
    if kind == "personal":
        if str(user.id) != owner_id:
            raise HTTPException(status_code=404, detail="Not found")
    elif kind == "channel":
        require_channel_role(session, user, uuid.UUID(owner_id), allowed=_ANY_MEMBER)
    else:
        raise HTTPException(status_code=404, detail="Not found")
    return commitment


@router.post("/commitments/{commitment_id}/resolve", response_model=CommitmentOut)
def mark_resolved(
    commitment_id: uuid.UUID,
    payload: CommitmentResolve,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommitmentOut:
    return resolve_commitment(session, _authorized(session, commitment_id, user), reason=payload.reason)


@router.post("/commitments/{commitment_id}/dismiss", response_model=CommitmentOut)
def mark_dismissed(
    commitment_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommitmentOut:
    """Different from resolved: "this never mattered" is not "this got done",
    and the record has to keep them apart to stay useful."""
    return dismiss_commitment(session, _authorized(session, commitment_id, user))


@router.post("/commitments/{commitment_id}/reopen", response_model=CommitmentOut)
def mark_reopened(
    commitment_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommitmentOut:
    return reopen_commitment(session, _authorized(session, commitment_id, user))
