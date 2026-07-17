"""Team = Channel (IA.md v2 §2.4): create/list within a Workspace, join/leave
freely (open by default - any Workspace member can join any Team in it
without an invite).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_workspace_membership
from app.core.slugs import unique_slug
from app.models.team import Team, TeamMembership
from app.models.user import User
from app.schemas.team import TeamCreate, TeamOut

router = APIRouter(tags=["teams"])


def _to_team_out(session: Session, team: Team, user: User) -> TeamOut:
    member_count = session.execute(
        select(func.count()).select_from(TeamMembership).where(TeamMembership.team_id == team.id)
    ).scalar_one()
    is_member = session.execute(
        select(TeamMembership).where(TeamMembership.team_id == team.id, TeamMembership.user_id == user.id)
    ).scalar_one_or_none() is not None
    return TeamOut(
        id=team.id, workspace_id=team.workspace_id, name=team.name, slug=team.slug,
        member_count=member_count, is_member=is_member,
    )


@router.get("/workspaces/{workspace_id}/teams", response_model=list[TeamOut])
def list_teams(
    workspace_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TeamOut]:
    require_workspace_membership(session, user, workspace_id)
    teams = session.execute(select(Team).where(Team.workspace_id == workspace_id)).scalars().all()
    return [_to_team_out(session, t, user) for t in teams]


@router.post("/workspaces/{workspace_id}/teams", response_model=TeamOut, status_code=201)
def create_team(
    workspace_id: uuid.UUID,
    payload: TeamCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamOut:
    require_workspace_membership(session, user, workspace_id)

    team = Team(workspace_id=workspace_id, name=payload.name, slug=unique_slug(payload.name))
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=user.id))  # creator auto-joins
    session.commit()
    session.refresh(team)
    return _to_team_out(session, team, user)


@router.post("/teams/{team_id}/join", response_model=TeamOut)
def join_team(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamOut:
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    require_workspace_membership(session, user, team.workspace_id)

    existing = session.execute(
        select(TeamMembership).where(TeamMembership.team_id == team_id, TeamMembership.user_id == user.id)
    ).scalar_one_or_none()
    if existing is None:
        session.add(TeamMembership(team_id=team_id, user_id=user.id))
        session.commit()
    return _to_team_out(session, team, user)


@router.post("/teams/{team_id}/leave", status_code=204)
def leave_team(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    require_workspace_membership(session, user, team.workspace_id)

    membership = session.execute(
        select(TeamMembership).where(TeamMembership.team_id == team_id, TeamMembership.user_id == user.id)
    ).scalar_one_or_none()
    if membership is not None:
        session.delete(membership)
        session.commit()
