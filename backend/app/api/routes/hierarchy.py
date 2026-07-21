"""Phase 2y: Class and Group routes, plus the navigation tree.

Route shapes mirror the hierarchy rather than flattening it:

    /workspaces/{workspace_id}/classes
    /workspaces/{workspace_id}/classes/{class_id}/groups
    /workspaces/{workspace_id}/tree

A Group is never addressed without its Class, and a Class never without its
Workspace. That isn't decoration - the parent in the path *is* the
authorization scope, so an id from another tenant produces a 404 at
resolution time instead of relying on a check further down that someone
might forget to write.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_channel_role, require_workspace_membership, require_workspace_role
from app.models.hierarchy import Group
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.schemas.hierarchy import (
    ChannelPathOut,
    ClassCreate,
    ClassOut,
    ClassUpdate,
    GroupCreate,
    GroupOut,
    GroupUpdate,
    TreeChannelOut,
    TreeClassOut,
    TreeGroupOut,
)
from app.services.channel_management import visible_teams_filter
from app.services.hierarchy import (
    CLASS_MANAGER_ROLES,
    channel_path,
    GROUP_MANAGER_ROLES,
    WORKSPACE_ADMIN_ROLES,
    HierarchyError,
    create_class,
    create_group,
    delete_class,
    delete_group,
    get_class_in_workspace,
    get_group_in_class,
    list_classes,
    list_groups,
    update_class,
    update_group,
    workspace_tree,
)

router = APIRouter(tags=["hierarchy"])


def _class_out(session: Session, workspace_class) -> ClassOut:
    group_count = session.execute(
        select(func.count()).select_from(Group).where(Group.class_id == workspace_class.id)
    ).scalar_one()
    return ClassOut(
        id=workspace_class.id, workspace_id=workspace_class.workspace_id,
        name=workspace_class.name, slug=workspace_class.slug,
        description=workspace_class.description, icon=workspace_class.icon,
        position=workspace_class.position, group_count=group_count,
    )


def _group_out(session: Session, group: Group) -> GroupOut:
    channel_count = session.execute(
        select(func.count()).select_from(Team).where(Team.group_id == group.id, Team.is_archived.is_(False))
    ).scalar_one()
    return GroupOut(
        id=group.id, class_id=group.class_id, name=group.name, slug=group.slug,
        description=group.description, icon=group.icon,
        position=group.position, channel_count=channel_count,
    )


def _resolve_class(session: Session, workspace_id: uuid.UUID, class_id: uuid.UUID):
    workspace_class = get_class_in_workspace(session, workspace_id, class_id)
    if workspace_class is None:
        raise HTTPException(status_code=404, detail="Class not found")
    return workspace_class


def _resolve_group(session: Session, workspace_id: uuid.UUID, class_id: uuid.UUID, group_id: uuid.UUID) -> Group:
    _resolve_class(session, workspace_id, class_id)  # proves the class is in this workspace first
    group = get_group_in_class(session, class_id, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


# --- classes --------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/classes", response_model=list[ClassOut])
def list_workspace_classes(
    workspace_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ClassOut]:
    require_workspace_membership(session, user, workspace_id)
    return [_class_out(session, c) for c in list_classes(session, workspace_id)]


@router.post("/workspaces/{workspace_id}/classes", response_model=ClassOut, status_code=201)
def create_workspace_class(
    workspace_id: uuid.UUID,
    payload: ClassCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ClassOut:
    require_workspace_role(session, user, workspace_id, allowed=CLASS_MANAGER_ROLES)
    try:
        workspace_class = create_class(
            session, workspace_id=workspace_id, creator=user,
            name=payload.name, description=payload.description, icon=payload.icon,
        )
    except HierarchyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _class_out(session, workspace_class)


@router.patch("/workspaces/{workspace_id}/classes/{class_id}", response_model=ClassOut)
def update_workspace_class(
    workspace_id: uuid.UUID,
    class_id: uuid.UUID,
    payload: ClassUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ClassOut:
    require_workspace_role(session, user, workspace_id, allowed=CLASS_MANAGER_ROLES)
    workspace_class = _resolve_class(session, workspace_id, class_id)
    try:
        workspace_class = update_class(
            session, workspace_class,
            name=payload.name, description=payload.description,
            icon=payload.icon, position=payload.position,
        )
    except HierarchyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _class_out(session, workspace_class)


@router.delete("/workspaces/{workspace_id}/classes/{class_id}", status_code=204)
def delete_workspace_class(
    workspace_id: uuid.UUID,
    class_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_workspace_role(session, user, workspace_id, allowed=CLASS_MANAGER_ROLES)
    workspace_class = _resolve_class(session, workspace_id, class_id)
    try:
        delete_class(session, workspace_class)
    except HierarchyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- groups ---------------------------------------------------------------


@router.get("/workspaces/{workspace_id}/classes/{class_id}/groups", response_model=list[GroupOut])
def list_class_groups(
    workspace_id: uuid.UUID,
    class_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[GroupOut]:
    require_workspace_membership(session, user, workspace_id)
    _resolve_class(session, workspace_id, class_id)
    return [_group_out(session, g) for g in list_groups(session, class_id)]


@router.post("/workspaces/{workspace_id}/classes/{class_id}/groups", response_model=GroupOut, status_code=201)
def create_class_group(
    workspace_id: uuid.UUID,
    class_id: uuid.UUID,
    payload: GroupCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GroupOut:
    require_workspace_role(session, user, workspace_id, allowed=GROUP_MANAGER_ROLES)
    workspace_class = _resolve_class(session, workspace_id, class_id)
    try:
        group = create_group(
            session, workspace_class=workspace_class, creator=user,
            name=payload.name, description=payload.description, icon=payload.icon,
        )
    except HierarchyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _group_out(session, group)


@router.patch("/workspaces/{workspace_id}/classes/{class_id}/groups/{group_id}", response_model=GroupOut)
def update_class_group(
    workspace_id: uuid.UUID,
    class_id: uuid.UUID,
    group_id: uuid.UUID,
    payload: GroupUpdate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> GroupOut:
    require_workspace_role(session, user, workspace_id, allowed=GROUP_MANAGER_ROLES)
    group = _resolve_group(session, workspace_id, class_id, group_id)
    try:
        group = update_group(
            session, group,
            name=payload.name, description=payload.description,
            icon=payload.icon, position=payload.position,
        )
    except HierarchyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _group_out(session, group)


@router.delete("/workspaces/{workspace_id}/classes/{class_id}/groups/{group_id}", status_code=204)
def delete_class_group(
    workspace_id: uuid.UUID,
    class_id: uuid.UUID,
    group_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_workspace_role(session, user, workspace_id, allowed=GROUP_MANAGER_ROLES)
    group = _resolve_group(session, workspace_id, class_id, group_id)
    try:
        delete_group(session, group)
    except HierarchyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- the navigation tree --------------------------------------------------


@router.get("/workspaces/{workspace_id}/tree", response_model=list[TreeClassOut])
def get_workspace_tree(
    workspace_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TreeClassOut]:
    """Classes -> Groups -> Channels for the navigation sidebar, in one call.

    Channel visibility reuses `visible_teams_filter` rather than
    reimplementing it - private channels stay hidden from non-members here
    exactly as they are in the flat channel list, because it is literally
    the same function.
    """
    membership = require_workspace_membership(session, user, workspace_id)
    visible = visible_teams_filter(
        session, workspace_id, user.id, is_workspace_admin=membership.role in WORKSPACE_ADMIN_ROLES
    )

    my_team_ids = set(
        session.execute(select(TeamMembership.team_id).where(TeamMembership.user_id == user.id)).scalars()
    )
    counts = dict(
        session.execute(
            select(TeamMembership.team_id, func.count()).group_by(TeamMembership.team_id)
        ).all()
    )

    return [
        TreeClassOut(
            id=c["id"], name=c["name"], slug=c["slug"], icon=c["icon"], description=c["description"],
            groups=[
                TreeGroupOut(
                    id=g["id"], name=g["name"], slug=g["slug"], icon=g["icon"], description=g["description"],
                    channels=[
                        TreeChannelOut(
                            id=t.id, name=t.name, slug=t.slug, icon=t.icon,
                            privacy=t.privacy.value,
                            is_member=t.id in my_team_ids,
                            member_count=counts.get(t.id, 0),
                        )
                        for t in g["channels"]
                    ],
                )
                for g in c["groups"]
            ],
        )
        for c in workspace_tree(session, workspace_id, visible)
    ]


@router.get("/teams/{team_id}/path", response_model=ChannelPathOut)
def get_channel_path(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChannelPathOut:
    """Where this Channel sits: Workspace / Class / Group / #Channel.

    Authorized as a channel read, not a workspace read - the breadcrumb
    names a Class and a Group, so it must not answer for a channel the
    caller can't open.
    """
    require_channel_role(session, user, team_id, allowed=[ChannelRole.CHANNEL_ADMIN, ChannelRole.CHANNEL_MEMBER])
    team = session.get(Team, team_id)
    path = channel_path(session, team)
    if path is None:
        # A channel whose chain is broken is a bug worth surfacing, not a
        # blank breadcrumb that quietly hides it.
        raise HTTPException(status_code=500, detail="This channel's group or class is missing")
    return ChannelPathOut(**path)
