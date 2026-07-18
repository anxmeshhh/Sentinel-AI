"""Phase 2l: assign a Workspace-level Connection to a specific Channel, and
allow-list specific resources within it (a GitHub repo, a Drive
file/folder, a Jira project) - see models/channel_connection.py for why this
is fail-closed by design.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_channel_role
from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
from app.models.connection import Connection
from app.models.team import ChannelRole, Team
from app.models.user import User
from app.schemas.channel_connection import (
    ChannelConnectionCreate,
    ChannelConnectionOut,
    ChannelConnectionResourceCreate,
    ChannelConnectionResourceOut,
)
from app.services.channel_connections import list_channel_connections

router = APIRouter(tags=["channel-connections"])

_ANY_MEMBER = [ChannelRole.CHANNEL_ADMIN, ChannelRole.CHANNEL_MEMBER]
_ADMIN_ONLY = [ChannelRole.CHANNEL_ADMIN]


def _to_out(channel_connection: ChannelConnection, connection: Connection, resources: list[ChannelConnectionResource]) -> ChannelConnectionOut:
    return ChannelConnectionOut(
        id=channel_connection.id,
        team_id=channel_connection.team_id,
        connection_id=connection.id,
        provider=connection.provider.value,
        label=connection.full_name,
        resources=[ChannelConnectionResourceOut.model_validate(r) for r in resources],
    )


@router.get("/teams/{team_id}/connections", response_model=list[ChannelConnectionOut])
def list_team_connections(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChannelConnectionOut]:
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    return [_to_out(cc, c, resources) for cc, c, resources in list_channel_connections(session, team_id)]


@router.post("/teams/{team_id}/connections", response_model=ChannelConnectionOut, status_code=201)
def assign_connection(
    team_id: uuid.UUID,
    payload: ChannelConnectionCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChannelConnectionOut:
    require_channel_role(session, user, team_id, allowed=_ADMIN_ONLY)

    team = session.get(Team, team_id)
    connection = session.get(Connection, payload.connection_id)
    if connection is None or connection.workspace_id != team.workspace_id:
        # A Connection from another Workspace can't be assigned here, even
        # by an admin - 404 rather than 403, consistent with this codebase's
        # "don't confirm existence of things outside the caller's scope"
        # convention elsewhere in deps.py.
        raise HTTPException(status_code=404, detail="Connection not found in this workspace")

    existing = session.query(ChannelConnection).filter_by(team_id=team_id, connection_id=payload.connection_id).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="This connection is already assigned to this channel")

    channel_connection = ChannelConnection(team_id=team_id, connection_id=payload.connection_id, added_by_user_id=user.id)
    session.add(channel_connection)
    session.commit()
    session.refresh(channel_connection)
    return _to_out(channel_connection, connection, [])


@router.delete("/teams/{team_id}/connections/{channel_connection_id}", status_code=204)
def unassign_connection(
    team_id: uuid.UUID,
    channel_connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_channel_role(session, user, team_id, allowed=_ADMIN_ONLY)

    channel_connection = session.get(ChannelConnection, channel_connection_id)
    if channel_connection is None or channel_connection.team_id != team_id:
        raise HTTPException(status_code=404, detail="Not found")

    session.delete(channel_connection)  # cascades to its resources
    session.commit()


@router.post("/teams/{team_id}/connections/{channel_connection_id}/resources", response_model=ChannelConnectionResourceOut, status_code=201)
def add_allowed_resource(
    team_id: uuid.UUID,
    channel_connection_id: uuid.UUID,
    payload: ChannelConnectionResourceCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChannelConnectionResourceOut:
    require_channel_role(session, user, team_id, allowed=_ADMIN_ONLY)

    channel_connection = session.get(ChannelConnection, channel_connection_id)
    if channel_connection is None or channel_connection.team_id != team_id:
        raise HTTPException(status_code=404, detail="Not found")

    existing = session.query(ChannelConnectionResource).filter_by(
        channel_connection_id=channel_connection_id, resource_key=payload.resource_key
    ).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="This resource is already allow-listed")

    resource = ChannelConnectionResource(
        channel_connection_id=channel_connection_id, resource_key=payload.resource_key, resource_label=payload.resource_label
    )
    session.add(resource)
    session.commit()
    session.refresh(resource)
    return ChannelConnectionResourceOut.model_validate(resource)


@router.delete("/teams/{team_id}/connections/{channel_connection_id}/resources/{resource_id}", status_code=204)
def remove_allowed_resource(
    team_id: uuid.UUID,
    channel_connection_id: uuid.UUID,
    resource_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_channel_role(session, user, team_id, allowed=_ADMIN_ONLY)

    resource = session.get(ChannelConnectionResource, resource_id)
    if resource is None or resource.channel_connection_id != channel_connection_id:
        raise HTTPException(status_code=404, detail="Not found")

    session.delete(resource)
    session.commit()
