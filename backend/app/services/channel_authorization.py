"""Phase 2z: the one place a Channel's authorized connections are resolved.

A Channel can see a connection assigned at three tiers, and its effective
authorization is the UNION up its own branch of the tree:

    the Channel's own ChannelConnection      (channel tier, Phase 2l)
  ∪ its Group's SharedConnection             (group tier, Phase 2z)
  ∪ its Class's SharedConnection             (class tier, Phase 2z)

Every consumer that used to read `ChannelConnection where team_id` directly -
`_channel_scope`, `is_resource_allowed`, the orchestrator's `_get_connection`
- now goes through here instead, so inheritance is enforced in exactly one
place. A connection assigned to a sibling class, or a group in another
class, simply never appears in the union.

Resource allow-lists merge across tiers: if the Class allows folder A and
the Channel allows file B on the same Drive connection, the channel may see
both. Fail-closed is preserved - a connection present at any tier with *no*
allow-listed resources anywhere authorizes no resource-gated file.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import SharedConnection, SharedConnectionResource, SharedScope
from app.models.team import Team


@dataclass
class AuthorizedConnection:
    connection: Connection
    resources: set[str] = field(default_factory=set)
    # Where this authorization comes from, for the UI ("inherited from Class").
    # If a connection is authorized at several tiers, the most specific wins
    # for display; resources still merge across all of them.
    source: str = "channel"  # "channel" | "group" | "class"


_SOURCE_RANK = {"class": 0, "group": 1, "channel": 2}


def _channel_lineage(session: Session, team_id: uuid.UUID) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """(group_id, class_id) for a channel, or (None, None) if the chain is
    broken. One query - the tree is shallow."""
    row = session.execute(
        select(Team.group_id, Group.class_id)
        .join(Group, Group.id == Team.group_id)
        .where(Team.id == team_id)
    ).first()
    if row is None:
        return None, None
    return row[0], row[1]


def authorized_connections(session: Session, team_id: uuid.UUID) -> dict[uuid.UUID, AuthorizedConnection]:
    """connection_id -> AuthorizedConnection, unioned across all three tiers."""
    group_id, class_id = _channel_lineage(session, team_id)
    result: dict[uuid.UUID, AuthorizedConnection] = {}

    def merge(connection: Connection, resource_keys: set[str], source: str) -> None:
        existing = result.get(connection.id)
        if existing is None:
            result[connection.id] = AuthorizedConnection(connection=connection, resources=set(resource_keys), source=source)
        else:
            existing.resources |= resource_keys
            # A more specific source wins for the label.
            if _SOURCE_RANK[source] > _SOURCE_RANK[existing.source]:
                existing.source = source

    # Class tier.
    if class_id is not None:
        for sc, connection in _shared_rows(session, SharedScope.CLASS, class_id):
            merge(connection, _shared_resource_keys(session, sc.id), "class")
    # Group tier.
    if group_id is not None:
        for sc, connection in _shared_rows(session, SharedScope.GROUP, group_id):
            merge(connection, _shared_resource_keys(session, sc.id), "group")
    # Channel tier.
    for cc, connection in _channel_rows(session, team_id):
        merge(connection, _channel_resource_keys(session, cc.id), "channel")

    return result


def _shared_rows(session: Session, scope: SharedScope, scope_id: uuid.UUID):
    return session.execute(
        select(SharedConnection, Connection)
        .join(Connection, Connection.id == SharedConnection.connection_id)
        .where(SharedConnection.scope_type == scope, SharedConnection.scope_id == scope_id)
    ).all()


def _channel_rows(session: Session, team_id: uuid.UUID):
    return session.execute(
        select(ChannelConnection, Connection)
        .join(Connection, Connection.id == ChannelConnection.connection_id)
        .where(ChannelConnection.team_id == team_id)
    ).all()


def _shared_resource_keys(session: Session, shared_connection_id: uuid.UUID) -> set[str]:
    return set(session.execute(
        select(SharedConnectionResource.resource_key).where(SharedConnectionResource.shared_connection_id == shared_connection_id)
    ).scalars())


def _channel_resource_keys(session: Session, channel_connection_id: uuid.UUID) -> set[str]:
    return set(session.execute(
        select(ChannelConnectionResource.resource_key).where(ChannelConnectionResource.channel_connection_id == channel_connection_id)
    ).scalars())


# --- the shapes the existing consumers expect -----------------------------


def resolve_channel_scope(session: Session, team_id: uuid.UUID) -> dict:
    """The `_channel_scope` shape (connections/providers/labels/
    allowed_resources), now unioned across tiers. channel_briefing delegates
    to this so feed/briefing/insights/knowledge inherit for free."""
    authorized = authorized_connections(session, team_id)
    providers: set[Provider] = set()
    connection_ids: set[uuid.UUID] = set()
    labels: list[str] = []
    allowed_resources: dict[uuid.UUID, set[str]] = {}
    for conn_id, auth in authorized.items():
        providers.add(auth.connection.provider)
        connection_ids.add(conn_id)
        labels.append(f"{auth.connection.provider.value}:{auth.connection.full_name}")
        if auth.resources:
            allowed_resources[conn_id] = auth.resources
    return {
        "connections": connection_ids,
        "providers": providers,
        "labels": labels,
        "allowed_resources": allowed_resources,
    }


def connection_authorized_for_channel(session: Session, team_id: uuid.UUID, connection_id: uuid.UUID) -> bool:
    """Is this connection authorized for this channel at any tier?"""
    return connection_id in authorized_connections(session, team_id)


def resource_authorized_for_channel(session: Session, team_id: uuid.UUID, connection_id: uuid.UUID, resource_key: str) -> bool:
    """Fail-closed resource check across all tiers: the connection must be
    authorized AND the resource_key allow-listed at some tier."""
    auth = authorized_connections(session, team_id).get(connection_id)
    if auth is None:
        return False
    return resource_key in auth.resources
