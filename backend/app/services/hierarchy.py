"""Phase 2y: Class and Group management, and the resolution helpers that
keep the Workspace -> Class -> Group -> Channel chain honest.

## The single rule this module exists to enforce

Every lookup is *scoped by its parent*. A Class is only ever fetched with a
workspace, a Group only ever with a class, a Channel only ever with a group.
Fetching by bare id and checking ownership afterwards is the same thing
right up until someone forgets the second half - so the unsafe version isn't
offered.

That is what makes cross-workspace, cross-class and cross-group access
structurally impossible rather than defended against: a Group id from
another workspace doesn't fail an ownership check, it simply isn't found.

## Not-found, not forbidden

Consistent with the rest of this codebase (see `deps.require_workspace_membership`),
a resource outside the caller's scope returns 404 rather than 403. Telling a
stranger "that exists but you can't have it" confirms the existence of another
tenant's Class.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.slugs import unique_slug
from app.models.hierarchy import Group, WorkspaceClass
from app.models.team import Team
from app.models.user import User
from app.models.workspace import Role, Workspace, WorkspaceKind

# Who may reshape the organization. Classes are a workspace-wide structural
# concern, so they stay with workspace admins; Groups are a team-structure
# concern, which is precisely what a team_manager is for.
CLASS_MANAGER_ROLES = (Role.SUPER_ADMIN, Role.ORG_ADMIN)
GROUP_MANAGER_ROLES = (Role.SUPER_ADMIN, Role.ORG_ADMIN, Role.TEAM_MANAGER)

# Sees every Channel in the workspace regardless of channel membership -
# same set the flat channel list already uses, kept here so the tree and the
# list can never drift apart.
WORKSPACE_ADMIN_ROLES = (Role.SUPER_ADMIN, Role.ORG_ADMIN)


class HierarchyError(ValueError):
    """Invalid hierarchy operation - routes translate this to a 400."""


def reject_if_personal(session: Session, workspace_id: uuid.UUID) -> Workspace:
    """A Personal Workspace has no org chart.

    Same guarantee Phase 2x made for Channels, extended to the two new
    levels. A Personal workspace is single-occupancy and holds that person's
    private connections; letting it grow Classes and Groups would create the
    shared structure that invitations are already refused for, and every
    reason that made channels unsafe there applies identically.
    """
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise HierarchyError("Workspace not found")
    if workspace.kind == WorkspaceKind.PERSONAL:
        raise HierarchyError("Personal workspaces are private and can't contain classes, groups or channels")
    return workspace


# --- scoped resolution ----------------------------------------------------


def get_class_in_workspace(session: Session, workspace_id: uuid.UUID, class_id: uuid.UUID) -> WorkspaceClass | None:
    return session.execute(
        select(WorkspaceClass).where(WorkspaceClass.id == class_id, WorkspaceClass.workspace_id == workspace_id)
    ).scalar_one_or_none()


def get_group_in_class(session: Session, class_id: uuid.UUID, group_id: uuid.UUID) -> Group | None:
    return session.execute(
        select(Group).where(Group.id == group_id, Group.class_id == class_id)
    ).scalar_one_or_none()


def get_group_in_workspace(session: Session, workspace_id: uuid.UUID, group_id: uuid.UUID) -> Group | None:
    """A Group reached through its Class's workspace - the join is the check.

    Used by channel creation, where the caller names a Group and the
    workspace comes from their session. A Group belonging to another
    workspace produces no row, so it can never parent a channel here.
    """
    return session.execute(
        select(Group)
        .join(WorkspaceClass, WorkspaceClass.id == Group.class_id)
        .where(Group.id == group_id, WorkspaceClass.workspace_id == workspace_id)
    ).scalar_one_or_none()


def workspace_id_for_group(session: Session, group_id: uuid.UUID) -> uuid.UUID | None:
    """The authoritative workspace for a Group, derived through its Class.

    This is the *only* place a Channel's denormalized `workspace_id` is
    allowed to come from.
    """
    return session.execute(
        select(WorkspaceClass.workspace_id)
        .join(Group, Group.class_id == WorkspaceClass.id)
        .where(Group.id == group_id)
    ).scalar_one_or_none()


# --- classes --------------------------------------------------------------


def list_classes(session: Session, workspace_id: uuid.UUID) -> list[WorkspaceClass]:
    return list(
        session.execute(
            select(WorkspaceClass)
            .where(WorkspaceClass.workspace_id == workspace_id)
            .order_by(WorkspaceClass.position, WorkspaceClass.created_at)
        ).scalars()
    )


def create_class(
    session: Session, *, workspace_id: uuid.UUID, creator: User,
    name: str, description: str | None = None, icon: str | None = None,
) -> WorkspaceClass:
    reject_if_personal(session, workspace_id)
    if not name.strip():
        raise HierarchyError("Class name can't be empty")

    next_position = session.execute(
        select(func.coalesce(func.max(WorkspaceClass.position), -1) + 1).where(WorkspaceClass.workspace_id == workspace_id)
    ).scalar_one()

    workspace_class = WorkspaceClass(
        workspace_id=workspace_id, name=name.strip(), slug=unique_slug(name),
        description=description or None, icon=icon or None,
        position=next_position, created_by_user_id=creator.id,
    )
    session.add(workspace_class)
    session.commit()
    session.refresh(workspace_class)
    return workspace_class


def update_class(
    session: Session, workspace_class: WorkspaceClass, *,
    name: str | None = None, description: str | None = None,
    icon: str | None = None, position: int | None = None,
) -> WorkspaceClass:
    if name is not None:
        if not name.strip():
            raise HierarchyError("Class name can't be empty")
        workspace_class.name = name.strip()
    if description is not None:
        workspace_class.description = description or None
    if icon is not None:
        workspace_class.icon = icon or None
    if position is not None:
        workspace_class.position = position
    session.commit()
    session.refresh(workspace_class)
    return workspace_class


def delete_class(session: Session, workspace_class: WorkspaceClass) -> None:
    """Refuses while it still contains Groups.

    Cascading would delete Channels - and with them their connection
    assignments, requirements and AI history - two levels below what the
    admin actually clicked on. Deleting a department should not silently
    destroy every team's operational context inside it, so the admin is made
    to empty it first and see what they're removing.
    """
    group_count = session.execute(
        select(func.count()).select_from(Group).where(Group.class_id == workspace_class.id)
    ).scalar_one()
    if group_count:
        raise HierarchyError(
            f"This class still contains {group_count} group{'s' if group_count != 1 else ''}. "
            "Move or delete them first."
        )
    session.delete(workspace_class)
    session.commit()


# --- groups ---------------------------------------------------------------


def list_groups(session: Session, class_id: uuid.UUID) -> list[Group]:
    return list(
        session.execute(
            select(Group).where(Group.class_id == class_id).order_by(Group.position, Group.created_at)
        ).scalars()
    )


def create_group(
    session: Session, *, workspace_class: WorkspaceClass, creator: User,
    name: str, description: str | None = None, icon: str | None = None,
) -> Group:
    reject_if_personal(session, workspace_class.workspace_id)
    if not name.strip():
        raise HierarchyError("Group name can't be empty")

    next_position = session.execute(
        select(func.coalesce(func.max(Group.position), -1) + 1).where(Group.class_id == workspace_class.id)
    ).scalar_one()

    group = Group(
        class_id=workspace_class.id, name=name.strip(), slug=unique_slug(name),
        description=description or None, icon=icon or None,
        position=next_position, created_by_user_id=creator.id,
    )
    session.add(group)
    session.commit()
    session.refresh(group)
    return group


def update_group(
    session: Session, group: Group, *,
    name: str | None = None, description: str | None = None,
    icon: str | None = None, position: int | None = None,
) -> Group:
    if name is not None:
        if not name.strip():
            raise HierarchyError("Group name can't be empty")
        group.name = name.strip()
    if description is not None:
        group.description = description or None
    if icon is not None:
        group.icon = icon or None
    if position is not None:
        group.position = position
    session.commit()
    session.refresh(group)
    return group


def delete_group(session: Session, group: Group) -> None:
    """Refuses while it still contains Channels - same reasoning as
    delete_class: the blast radius of a cascade here is somebody's channel
    history, not just a folder."""
    channel_count = session.execute(
        select(func.count()).select_from(Team).where(Team.group_id == group.id)
    ).scalar_one()
    if channel_count:
        raise HierarchyError(
            f"This group still contains {channel_count} channel{'s' if channel_count != 1 else ''}. "
            "Move or delete them first."
        )
    session.delete(group)
    session.commit()


# --- the whole tree, for navigation --------------------------------------


def workspace_tree(session: Session, workspace_id: uuid.UUID, visible_teams: list[Team]) -> list[dict]:
    """Classes -> Groups -> Channels, for the navigation sidebar.

    Takes the already-filtered list of Channels the caller may see rather
    than querying them itself: channel visibility (private/archived/
    membership) is decided by `visible_teams_filter`, and re-deriving it
    here would be a second implementation of a permission rule that must
    only have one.

    Empty Classes and Groups are still returned - an admin who just created
    "Marketing" needs to see it in order to put a Group in it.
    """
    by_group: dict[uuid.UUID, list[Team]] = {}
    for team in visible_teams:
        by_group.setdefault(team.group_id, []).append(team)

    classes = list_classes(session, workspace_id)
    groups_by_class: dict[uuid.UUID, list[Group]] = {}
    if classes:
        for group in session.execute(
            select(Group)
            .where(Group.class_id.in_([c.id for c in classes]))
            .order_by(Group.position, Group.created_at)
        ).scalars():
            groups_by_class.setdefault(group.class_id, []).append(group)

    return [
        {
            "id": c.id,
            "name": c.name,
            "slug": c.slug,
            "icon": c.icon,
            "description": c.description,
            "groups": [
                {
                    "id": g.id,
                    "name": g.name,
                    "slug": g.slug,
                    "icon": g.icon,
                    "description": g.description,
                    "channels": sorted(by_group.get(g.id, []), key=lambda t: t.name),
                }
                for g in groups_by_class.get(c.id, [])
            ],
        }
        for c in classes
    ]


def channel_path(session: Session, team: Team) -> dict | None:
    """The breadcrumb for one Channel: its Group, Class and Workspace.

    Returns None if the chain is broken, which the API surfaces rather than
    papering over - a Channel that can't state where it lives is a bug worth
    seeing, not a blank breadcrumb.
    """
    row = session.execute(
        select(Workspace, WorkspaceClass, Group)
        .join(WorkspaceClass, WorkspaceClass.workspace_id == Workspace.id)
        .join(Group, Group.class_id == WorkspaceClass.id)
        .where(Group.id == team.group_id)
    ).first()
    if row is None:
        return None
    workspace, workspace_class, group = row
    return {
        "workspace_id": workspace.id, "workspace_name": workspace.name,
        "class_id": workspace_class.id, "class_name": workspace_class.name,
        "group_id": group.id, "group_name": group.name,
        "channel_id": team.id, "channel_name": team.name,
    }
