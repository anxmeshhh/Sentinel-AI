"""Team = Channel (IA.md v2 §2.4): create/list within a Workspace, join/leave
freely (open by default - any Workspace member can join any Team in it
without an invite).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_channel_role, require_workspace_membership
from app.core.slugs import unique_slug
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Workspace
from app.schemas.team import MyTeamOut, TeamCreate, TeamMemberOut, TeamMemberRoleUpdate, TeamOut

router = APIRouter(tags=["teams"])


def _to_team_out(session: Session, team: Team, user: User) -> TeamOut:
    member_count = session.execute(
        select(func.count()).select_from(TeamMembership).where(TeamMembership.team_id == team.id)
    ).scalar_one()
    my_membership = session.execute(
        select(TeamMembership).where(TeamMembership.team_id == team.id, TeamMembership.user_id == user.id)
    ).scalar_one_or_none()
    return TeamOut(
        id=team.id, workspace_id=team.workspace_id, name=team.name, slug=team.slug,
        member_count=member_count, is_member=my_membership is not None,
        my_channel_role=my_membership.role.value if my_membership else None,
    )


@router.get("/teams/mine", response_model=list[MyTeamOut])
def list_my_teams(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MyTeamOut]:
    """Every team the user belongs to, across every workspace - the "My
    Channels" dashboard section needs this precisely because it has no
    single active workspace to scope by (that's the whole point: jump into
    any channel without first navigating through its parent group).
    """
    rows = session.execute(
        select(Team, Workspace.name, Membership.role, TeamMembership.role)
        .join(TeamMembership, TeamMembership.team_id == Team.id)
        .join(Workspace, Workspace.id == Team.workspace_id)
        .join(Membership, (Membership.workspace_id == Workspace.id) & (Membership.user_id == user.id))
        .where(TeamMembership.user_id == user.id)
    ).all()

    result = []
    for team, workspace_name, workspace_role, channel_role in rows:
        member_count = session.execute(
            select(func.count()).select_from(TeamMembership).where(TeamMembership.team_id == team.id)
        ).scalar_one()
        result.append(
            MyTeamOut(
                id=team.id, workspace_id=team.workspace_id, workspace_name=workspace_name,
                name=team.name, slug=team.slug, member_count=member_count,
                role=workspace_role.value, channel_role=channel_role.value,
            )
        )
    return result


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

    team = Team(workspace_id=workspace_id, name=payload.name, slug=unique_slug(payload.name), created_by_user_id=user.id)
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=user.id, role=ChannelRole.CHANNEL_ADMIN))  # creator auto-joins as admin
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
        _reject_if_last_admin(session, team_id, membership)
        session.delete(membership)
        session.commit()


def _reject_if_last_admin(session: Session, team_id: uuid.UUID, membership: TeamMembership) -> None:
    """Stop a channel from being left admin-less: if this is the sole
    remaining channel_admin and other members would still be left behind,
    they'd have no one able to manage Connections/resources/roles for the
    channel going forward. Leaving/removal is still fine if it's the last
    member entirely - the channel just goes quiet, not un-manageable.
    """
    if membership.role != ChannelRole.CHANNEL_ADMIN:
        return
    other_admins = session.execute(
        select(func.count()).select_from(TeamMembership).where(
            TeamMembership.team_id == team_id,
            TeamMembership.role == ChannelRole.CHANNEL_ADMIN,
            TeamMembership.user_id != membership.user_id,
        )
    ).scalar_one()
    if other_admins > 0:
        return
    other_members = session.execute(
        select(func.count()).select_from(TeamMembership).where(
            TeamMembership.team_id == team_id, TeamMembership.user_id != membership.user_id
        )
    ).scalar_one()
    if other_members > 0:
        raise HTTPException(status_code=400, detail="You're the only Channel Admin - promote someone else first")


@router.get("/teams/{team_id}/members", response_model=list[TeamMemberOut])
def list_team_members(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TeamMemberOut]:
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    require_workspace_membership(session, user, team.workspace_id)

    rows = session.execute(
        select(User.id, User.name, User.email, TeamMembership.role)
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .where(TeamMembership.team_id == team_id)
    ).all()
    return [TeamMemberOut(user_id=uid, name=name, email=email, channel_role=role.value) for uid, name, email, role in rows]


@router.patch("/teams/{team_id}/members/{target_user_id}/role", response_model=TeamMemberOut)
def update_member_role(
    team_id: uuid.UUID,
    target_user_id: uuid.UUID,
    payload: TeamMemberRoleUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamMemberOut:
    require_channel_role(session, user, team_id, allowed=[ChannelRole.CHANNEL_ADMIN])
    try:
        new_role = ChannelRole(payload.channel_role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid channel_role: {payload.channel_role}")

    membership = session.execute(
        select(TeamMembership).where(TeamMembership.team_id == team_id, TeamMembership.user_id == target_user_id)
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="That user isn't a member of this channel")

    if new_role != ChannelRole.CHANNEL_ADMIN:
        _reject_if_last_admin(session, team_id, membership)

    membership.role = new_role
    session.commit()

    target_user = session.get(User, target_user_id)
    return TeamMemberOut(user_id=target_user_id, name=target_user.name, email=target_user.email, channel_role=new_role.value)


@router.delete("/teams/{team_id}/members/{target_user_id}", status_code=204)
def remove_team_member(
    team_id: uuid.UUID,
    target_user_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_channel_role(session, user, team_id, allowed=[ChannelRole.CHANNEL_ADMIN])

    membership = session.execute(
        select(TeamMembership).where(TeamMembership.team_id == team_id, TeamMembership.user_id == target_user_id)
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="That user isn't a member of this channel")

    _reject_if_last_admin(session, team_id, membership)
    session.delete(membership)
    session.commit()
