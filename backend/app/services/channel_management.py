"""Phase 2o: the single Channel create/update/archive/delete service.

The spec's explicit architecture requirement: manual UI and (future)
AI-assisted channel creation must share one underlying service -
"Do NOT create separate Channel management logic for manual and AI
workflows." Routes do the RBAC gating (require_workspace_role /
require_channel_role); this module does config validation and the actual
writes, so a future AI tool call lands here with identical semantics.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.slugs import unique_slug
from app.models.channel_ai_history import ChannelAIHistoryEntry
from app.models.channel_connection import ChannelConnection
from app.models.channel_required_connection import ChannelRequiredConnection
from app.models.connection import Connection
from app.models.invite import WorkspaceInvite
from app.models.team import ChannelPrivacy, ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership
from app.services.hierarchy import get_group_in_workspace


class ChannelConfigError(ValueError):
    """Invalid channel configuration - routes translate this to a 400."""


def create_channel(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    group_id: uuid.UUID,
    creator: User,
    name: str,
    description: str | None = None,
    icon: str | None = None,
    category: str | None = None,
    privacy: ChannelPrivacy = ChannelPrivacy.PUBLIC,
    member_user_ids: list[uuid.UUID] | None = None,
    admin_user_ids: list[uuid.UUID] | None = None,
    connection_ids: list[uuid.UUID] | None = None,
) -> Team:
    member_user_ids = list(member_user_ids or [])
    admin_user_ids = set(admin_user_ids or [])

    # Phase 2y: the parent Group decides the workspace, not the caller. A
    # Group in another workspace simply isn't found here, so a channel can
    # never be created across a tenant boundary - and the denormalized
    # `workspace_id` below cannot disagree with `group -> class -> workspace`
    # because it *is* that value.
    group = get_group_in_workspace(session, workspace_id, group_id)
    if group is None:
        raise ChannelConfigError("That group doesn't exist in this workspace")

    # Every configured member/admin must already be a member of the parent
    # Workspace - a Channel can't smuggle someone into a Group.
    if admin_user_ids - set(member_user_ids):
        member_user_ids.extend(admin_user_ids - set(member_user_ids))
    if member_user_ids:
        workspace_member_ids = set(
            session.execute(
                select(Membership.user_id).where(Membership.workspace_id == workspace_id, Membership.user_id.in_(member_user_ids))
            ).scalars()
        )
        outsiders = set(member_user_ids) - workspace_member_ids
        if outsiders:
            raise ChannelConfigError("Every channel member must already belong to this workspace")

    # Every assigned Connection must belong to this Workspace - same tenant
    # boundary Phase 2l enforces on later assignment.
    connection_ids = list(connection_ids or [])
    if connection_ids:
        owned = set(
            session.execute(
                select(Connection.id).where(Connection.workspace_id == workspace_id, Connection.id.in_(connection_ids))
            ).scalars()
        )
        if set(connection_ids) - owned:
            raise ChannelConfigError("Every assigned connection must belong to this workspace")

    team = Team(
        workspace_id=workspace_id,
        group_id=group.id,
        name=name,
        slug=unique_slug(name),
        created_by_user_id=creator.id,
        description=description,
        icon=icon,
        category=category,
        privacy=privacy,
    )
    session.add(team)
    session.flush()

    # Creator is always a member and always an admin - a channel must never
    # be born without someone able to manage it (2k's last-admin rule).
    roles: dict[uuid.UUID, ChannelRole] = {uid: ChannelRole.CHANNEL_MEMBER for uid in member_user_ids}
    for uid in admin_user_ids:
        roles[uid] = ChannelRole.CHANNEL_ADMIN
    roles[creator.id] = ChannelRole.CHANNEL_ADMIN

    for uid, role in roles.items():
        session.add(TeamMembership(team_id=team.id, user_id=uid, role=role))

    for connection_id in connection_ids:
        session.add(ChannelConnection(team_id=team.id, connection_id=connection_id, added_by_user_id=creator.id))

    session.commit()
    session.refresh(team)
    return team


def update_channel(
    session: Session,
    team: Team,
    *,
    name: str | None = None,
    description: str | None = None,
    icon: str | None = None,
    category: str | None = None,
    privacy: ChannelPrivacy | None = None,
) -> Team:
    """Partial update - only fields explicitly passed change. The slug is
    deliberately NOT regenerated on rename: it's referenced nowhere as a
    lookup key (ids are), and keeping it stable avoids breaking anything
    that displays it.
    """
    if name is not None:
        if not name.strip():
            raise ChannelConfigError("Channel name can't be empty")
        team.name = name.strip()
    if description is not None:
        team.description = description or None
    if icon is not None:
        team.icon = icon or None
    if category is not None:
        team.category = category or None
    if privacy is not None:
        team.privacy = privacy
    session.commit()
    session.refresh(team)
    return team


def set_archived(session: Session, team: Team, archived: bool) -> Team:
    team.is_archived = archived
    session.commit()
    session.refresh(team)
    return team


def delete_channel(session: Session, team: Team) -> None:
    """Hard delete, with explicit cleanup of every dependent table - none of
    these have DB-level ON DELETE CASCADE (the codebase convention is
    explicit deletes over schema-level cascades), so skipping any of them
    would leave orphaned rows or a foreign-key error.
    """
    session.query(ChannelAIHistoryEntry).filter(ChannelAIHistoryEntry.team_id == team.id).delete()
    for channel_connection in session.query(ChannelConnection).filter(ChannelConnection.team_id == team.id).all():
        session.delete(channel_connection)  # ORM-cascades to its allow-listed resources
    session.query(ChannelRequiredConnection).filter(ChannelRequiredConnection.team_id == team.id).delete()
    session.query(TeamMembership).filter(TeamMembership.team_id == team.id).delete()
    session.query(WorkspaceInvite).filter(WorkspaceInvite.team_id == team.id).delete()

    # Force the dependent deletes to hit the database before the parent.
    # There is no relationship() between Team and ChannelConnection - only a
    # bare FK column - so SQLAlchemy's unit of work doesn't know they're
    # ordered and can emit `DELETE FROM teams` first, which MySQL rejects.
    # Confirmed real: deleting a channel that had a connection assigned
    # failed with a foreign-key violation on MySQL while passing in tests,
    # because SQLite doesn't enforce foreign keys unless asked to.
    session.flush()

    session.delete(team)
    session.commit()


def visible_teams_filter(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID, *, is_workspace_admin: bool) -> list[Team]:
    """Channel visibility (spec: "Users should only see ... Channels they
    are authorized to access"): PUBLIC/INVITE_ONLY are listed for every
    workspace member; PRIVATE only for its own members - unless the caller
    is a workspace admin, who sees everything. Archived channels are
    excluded for everyone; they resurface only via direct link/unarchive.
    """
    teams = session.execute(
        select(Team).where(Team.workspace_id == workspace_id, Team.is_archived.is_(False))
    ).scalars().all()
    if is_workspace_admin:
        return list(teams)

    my_team_ids = set(
        session.execute(select(TeamMembership.team_id).where(TeamMembership.user_id == user_id)).scalars()
    )
    return [t for t in teams if t.privacy != ChannelPrivacy.PRIVATE or t.id in my_team_ids]
