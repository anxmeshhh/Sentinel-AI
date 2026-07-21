"""Query/permission-check helpers for Phase 2l's per-channel Connections.

Kept separate from the route handlers so Phase 2m's Channel AI orchestrator
can reuse `is_resource_allowed`/`list_channel_connections` directly, without
importing route-layer code - same separation the rest of the codebase uses
(routes call services, services never import routes).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
from app.models.connection import Connection


def list_channel_connections(session: Session, team_id: uuid.UUID) -> list[tuple[ChannelConnection, Connection, list[ChannelConnectionResource]]]:
    """Every Connection assigned to this Channel, with its allow-listed
    resources - the "which authorized Connections/resources does this
    Channel have" lookup that both the admin UI and the Channel AI need.
    """
    rows = session.execute(
        select(ChannelConnection, Connection)
        .join(Connection, Connection.id == ChannelConnection.connection_id)
        .where(ChannelConnection.team_id == team_id)
    ).all()

    result = []
    for channel_connection, connection in rows:
        resources = session.execute(
            select(ChannelConnectionResource).where(ChannelConnectionResource.channel_connection_id == channel_connection.id)
        ).scalars().all()
        result.append((channel_connection, connection, list(resources)))
    return result


def is_resource_allowed(session: Session, team_id: uuid.UUID, connection_id: uuid.UUID, resource_key: str) -> bool:
    """Fail-closed: a resource is only usable by this Channel if the
    Connection is authorized AND that exact resource_key is allow-listed.

    Phase 2z: delegates to channel_authorization so a resource allow-listed
    at the Channel's Group or Class counts too - the check is the union
    across tiers, not the channel row alone. Still fail-closed: no
    authorization, or authorization with no matching resource, both mean no.
    """
    from app.services.channel_authorization import resource_authorized_for_channel

    return resource_authorized_for_channel(session, team_id, connection_id, resource_key)
