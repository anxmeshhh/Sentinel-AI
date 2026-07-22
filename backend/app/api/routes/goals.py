"""Goal-Based AI routes.

Two scopes, as everywhere else, with one difference worth stating: creating a
*shared* goal is a channel-member action, but **closing** one is restricted to
channel admins. Declaring a team's objective achieved or abandoned is a
statement about everyone's work, not just the clicker's.

    GET    /goals                        your own (private)
    POST   /goals                        set one privately
    GET    /goals/{id}                   detail: health, evidence, blockers
    GET    /teams/{id}/goals             the channel's (shared)
    POST   /teams/{id}/goals             set one for the channel

    POST   /goals/{id}/commitments       link a commitment
    DELETE /goals/{id}/commitments/{cid} unlink
    POST   /goals/{id}/achieved|abandoned|reopen
    POST   /goals/{id}/investigate       why is this at risk?
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id, require_channel_role
from app.models.commitment import Commitment
from app.models.goal import Goal
from app.models.team import ChannelRole, Team
from app.models.user import User
from app.schemas.goal import GoalCreate, GoalDetailOut, GoalLinkCreate, GoalOut
from app.schemas.investigation import InvestigationOut
from app.services.goals import (
    NotAuthorized,
    close_goal,
    create_goal,
    goal_evidence,
    link_commitment,
    list_goals,
    reassess_goal,
    reopen_goal,
    unlink_commitment,
)
from app.services.investigation import (
    NotAuthorized as InvestigationNotAuthorized,
)
from app.services.investigation import (
    channel_scope,
    investigate_goal,
    personal_scope,
)

router = APIRouter(tags=["goals"])

_ANY_MEMBER = [ChannelRole.CHANNEL_ADMIN, ChannelRole.CHANNEL_MEMBER]
_ADMIN_ONLY = [ChannelRole.CHANNEL_ADMIN]


def _detail(session: Session, goal: Goal) -> GoalDetailOut:
    evidence = goal_evidence(session, goal)
    return GoalDetailOut(
        **GoalOut.model_validate(goal, from_attributes=True).model_dump(),
        commitments=evidence["commitments"],
        blockers=evidence["blockers"],
        risks=evidence["risks"],
    )


def _authorized(session: Session, goal_id: uuid.UUID, user: User, *, admin_for_channel: bool = False) -> Goal:
    """One rule for every goal action, read off the record's own scope_key."""
    goal = session.get(Goal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Not found")

    kind, _, owner_id = goal.scope_key.partition(":")
    if kind == "personal":
        if str(user.id) != owner_id:
            raise HTTPException(status_code=404, detail="Not found")
    elif kind == "channel":
        allowed = _ADMIN_ONLY if admin_for_channel else _ANY_MEMBER
        require_channel_role(session, user, uuid.UUID(owner_id), allowed=allowed)
    else:
        raise HTTPException(status_code=404, detail="Not found")
    return goal


def _scope_for(session: Session, goal: Goal):
    kind, _, owner_id = goal.scope_key.partition(":")
    if kind == "personal":
        return personal_scope(session, goal.workspace_id, uuid.UUID(owner_id))
    return channel_scope(session, uuid.UUID(owner_id))


# --- individual ------------------------------------------------------------


@router.get("/goals", response_model=list[GoalOut])
def my_goals(
    include_closed: bool = False,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[GoalOut]:
    return list_goals(session, personal_scope(session, workspace_id, user.id), include_closed=include_closed)


@router.post("/goals", response_model=GoalOut, status_code=201)
def add_my_goal(
    payload: GoalCreate,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> GoalOut:
    return create_goal(
        session, workspace_id=workspace_id, scope=personal_scope(session, workspace_id, user.id),
        title=payload.title, outcome=payload.outcome, due_at=payload.due_at, user_id=user.id,
    )


# --- channel ---------------------------------------------------------------


@router.get("/teams/{team_id}/goals", response_model=list[GoalOut])
def channel_goals(
    team_id: uuid.UUID,
    include_closed: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[GoalOut]:
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    return list_goals(session, channel_scope(session, team_id), include_closed=include_closed)


@router.post("/teams/{team_id}/goals", response_model=GoalOut, status_code=201)
def add_channel_goal(
    team_id: uuid.UUID,
    payload: GoalCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GoalOut:
    """Any member may state what the team is working toward."""
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    team = session.get(Team, team_id)
    return create_goal(
        session, workspace_id=team.workspace_id, scope=channel_scope(session, team_id),
        title=payload.title, outcome=payload.outcome, due_at=payload.due_at, user_id=user.id,
    )


# --- detail and evidence ---------------------------------------------------


@router.get("/goals/{goal_id}", response_model=GoalDetailOut)
def goal_detail(
    goal_id: uuid.UUID,
    refresh: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GoalDetailOut:
    goal = _authorized(session, goal_id, user)
    if refresh:
        reassess_goal(session, goal)
    return _detail(session, goal)


@router.post("/goals/{goal_id}/commitments", response_model=GoalDetailOut)
def add_link(
    goal_id: uuid.UUID,
    payload: GoalLinkCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GoalDetailOut:
    """Link a commitment. The service refuses any commitment from a different
    scope, which is what stops a private promise from moving a team goal."""
    goal = _authorized(session, goal_id, user)
    commitment = session.get(Commitment, payload.commitment_id)
    if commitment is None:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        link_commitment(session, goal, commitment, user.id)
    except NotAuthorized as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _detail(session, goal)


@router.delete("/goals/{goal_id}/commitments/{commitment_id}", response_model=GoalDetailOut)
def remove_link(
    goal_id: uuid.UUID,
    commitment_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GoalDetailOut:
    goal = _authorized(session, goal_id, user)
    unlink_commitment(session, goal, commitment_id)
    return _detail(session, goal)


# --- lifecycle -------------------------------------------------------------


@router.post("/goals/{goal_id}/achieved", response_model=GoalOut)
def mark_achieved(
    goal_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GoalOut:
    """A person's call, never Sentinel's - "done" is defined by whoever set
    the goal. Admin-only for a channel: declaring a team objective achieved
    is a statement about everyone's work."""
    return close_goal(session, _authorized(session, goal_id, user, admin_for_channel=True), achieved=True)


@router.post("/goals/{goal_id}/abandoned", response_model=GoalOut)
def mark_abandoned(
    goal_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GoalOut:
    return close_goal(session, _authorized(session, goal_id, user, admin_for_channel=True), achieved=False)


@router.post("/goals/{goal_id}/reopen", response_model=GoalOut)
def mark_reopened(
    goal_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GoalOut:
    return reopen_goal(session, _authorized(session, goal_id, user, admin_for_channel=True))


# --- investigate -----------------------------------------------------------


@router.post("/goals/{goal_id}/investigate", response_model=InvestigationOut)
def investigate(
    goal_id: uuid.UUID,
    refresh: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InvestigationOut:
    """Why is this goal at risk or blocked?

    Scope comes from the goal itself, so a private goal is investigated
    privately and a channel goal as the channel.
    """
    goal = _authorized(session, goal_id, user)
    try:
        return investigate_goal(session, goal=goal, scope=_scope_for(session, goal), refresh=refresh)
    except InvestigationNotAuthorized as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
