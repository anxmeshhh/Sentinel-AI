"""Team = Channel (IA.md v2 §2.4): create/list within a Workspace, join/leave
freely (open by default - any Workspace member can join any Team in it
without an invite).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_channel_role, require_workspace_membership, require_workspace_role
from app.models.team import ChannelPrivacy, ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.team import MyTeamOut, TeamCreate, TeamMemberOut, TeamMemberRoleUpdate, TeamOut, TeamUpdate
from app.services.channel_management import (
    ChannelConfigError,
    create_channel,
    delete_channel,
    set_archived,
    update_channel,
    visible_teams_filter,
)

router = APIRouter(tags=["teams"])

# Spec (Phase 2o): creating channels is a Group Owner/Admin capability, not
# an every-member one - team_manager included since managing team structure
# is literally that role's purpose.
CHANNEL_CREATOR_ROLES = [Role.SUPER_ADMIN, Role.ORG_ADMIN, Role.TEAM_MANAGER]
WORKSPACE_ADMIN_ROLES = (Role.SUPER_ADMIN, Role.ORG_ADMIN)


def _parse_privacy(value: str) -> ChannelPrivacy:
    try:
        return ChannelPrivacy(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid privacy: {value} (use public, invite_only, or private)")


def _to_team_out(session: Session, team: Team, user: User) -> TeamOut:
    member_count = session.execute(
        select(func.count()).select_from(TeamMembership).where(TeamMembership.team_id == team.id)
    ).scalar_one()
    my_membership = session.execute(
        select(TeamMembership).where(TeamMembership.team_id == team.id, TeamMembership.user_id == user.id)
    ).scalar_one_or_none()
    return TeamOut(
        id=team.id, workspace_id=team.workspace_id, group_id=team.group_id, name=team.name, slug=team.slug,
        member_count=member_count, is_member=my_membership is not None,
        my_channel_role=my_membership.role.value if my_membership else None,
        description=team.description, icon=team.icon, category=team.category,
        privacy=team.privacy.value, is_archived=team.is_archived,
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
        .where(TeamMembership.user_id == user.id, Team.is_archived.is_(False))
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
    membership = require_workspace_membership(session, user, workspace_id)
    teams = visible_teams_filter(
        session, workspace_id, user.id, is_workspace_admin=membership.role in WORKSPACE_ADMIN_ROLES
    )
    return [_to_team_out(session, t, user) for t in teams]


@router.get("/teams/{team_id}", response_model=TeamOut)
def get_team(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamOut:
    """Direct single-Channel lookup (Phase 2n) - the Channel workspace page
    is reachable by URL, so it needs to load its own header info without
    first fetching every Team in the Workspace. A PRIVATE channel 404s for
    non-members (Phase 2o) - same don't-confirm-existence convention as
    everywhere else; workspace admins excepted."""
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    membership = require_workspace_membership(session, user, team.workspace_id)

    if team.privacy == ChannelPrivacy.PRIVATE and membership.role not in WORKSPACE_ADMIN_ROLES:
        is_member = session.execute(
            select(TeamMembership).where(TeamMembership.team_id == team_id, TeamMembership.user_id == user.id)
        ).scalar_one_or_none() is not None
        if not is_member:
            raise HTTPException(status_code=404, detail="Team not found")
    return _to_team_out(session, team, user)


@router.patch("/teams/{team_id}", response_model=TeamOut)
def update_team(
    team_id: uuid.UUID,
    payload: TeamUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamOut:
    require_channel_role(session, user, team_id, allowed=[ChannelRole.CHANNEL_ADMIN])
    team = session.get(Team, team_id)
    try:
        team = update_channel(
            session, team,
            name=payload.name,
            description=payload.description,
            icon=payload.icon,
            category=payload.category,
            privacy=_parse_privacy(payload.privacy) if payload.privacy is not None else None,
        )
    except ChannelConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_team_out(session, team, user)


@router.post("/teams/{team_id}/archive", response_model=TeamOut)
def archive_team(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamOut:
    require_channel_role(session, user, team_id, allowed=[ChannelRole.CHANNEL_ADMIN])
    team = set_archived(session, session.get(Team, team_id), True)
    return _to_team_out(session, team, user)


@router.post("/teams/{team_id}/unarchive", response_model=TeamOut)
def unarchive_team(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamOut:
    require_channel_role(session, user, team_id, allowed=[ChannelRole.CHANNEL_ADMIN])
    team = set_archived(session, session.get(Team, team_id), False)
    return _to_team_out(session, team, user)


@router.delete("/teams/{team_id}", status_code=204)
def delete_team(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_channel_role(session, user, team_id, allowed=[ChannelRole.CHANNEL_ADMIN])
    delete_channel(session, session.get(Team, team_id))


@router.post("/workspaces/{workspace_id}/teams", response_model=TeamOut, status_code=201)
def create_team(
    workspace_id: uuid.UUID,
    payload: TeamCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TeamOut:
    require_workspace_role(session, user, workspace_id, allowed=CHANNEL_CREATOR_ROLES)

    # Channels are a sharing surface, and a Personal workspace holds the
    # user's own mailbox/calendar/files. A channel there would let those
    # personal Connections be assigned to it (the same-workspace check
    # passes), which is only harmless while the workspace stays
    # single-occupancy. Removing the surface is the durable fix rather than
    # relying on that staying true.
    workspace = session.get(Workspace, workspace_id)
    if workspace is not None and workspace.kind == WorkspaceKind.PERSONAL:
        raise HTTPException(
            status_code=400,
            detail="Channels live in Groups, not your Personal workspace. Create a Group to collaborate.",
        )

    try:
        team = create_channel(
            session,
            workspace_id=workspace_id,
            group_id=payload.group_id,
            creator=user,
            name=payload.name,
            description=payload.description,
            icon=payload.icon,
            category=payload.category,
            privacy=_parse_privacy(payload.privacy),
            member_user_ids=payload.member_user_ids,
            admin_user_ids=payload.admin_user_ids,
            connection_ids=payload.connection_ids,
        )
    except ChannelConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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
        # Phase 2o: open self-join is a PUBLIC-channel behavior only.
        # INVITE_ONLY/PRIVATE entry paths are an accepted invite (which
        # creates the TeamMembership itself) or an admin adding you.
        if team.is_archived:
            raise HTTPException(status_code=400, detail="This channel is archived")
        if team.privacy != ChannelPrivacy.PUBLIC:
            raise HTTPException(status_code=403, detail="This channel can only be joined by invite")
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
