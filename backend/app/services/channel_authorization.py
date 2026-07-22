"""The one place a Channel's authorized connections are resolved.

A Channel's effective authorization is the UNION up its own branch of the
tree, then NARROWED by anything explicitly excluded for that channel:

      its Workspace's SharedConnection       (workspace tier, Phase 3a)
    ∪ its Class's SharedConnection           (class tier, Phase 2z)
    ∪ its Group's SharedConnection           (group tier, Phase 2z)
    ∪ the Channel's own ChannelConnection    (channel tier, Phase 2l)
    − the Channel's ChannelConnectionExclusion   (narrowing, Phase 3a)

Every consumer that used to read `ChannelConnection where team_id` directly -
`_channel_scope`, `is_resource_allowed`, the orchestrator's `_get_connection`
- goes through here instead, so inheritance and exclusion are enforced in
exactly one place. A connection shared to a sibling class, another
workspace, or a group in another class simply never appears in the union.

## Why this stays fail-closed even with inheritance

Sharing is always an explicit admin act. Connecting a service grants
nothing anywhere by itself; someone must deliberately share it at a tier.
So a newly created Channel inherits only what an admin already chose to
make shared context - never "everything in the workspace" by default.

Resource allow-lists merge across tiers: if the Class allows folder A and
the Channel allows file B on the same Drive connection, the channel may see
both. Fail-closed is preserved - a connection present at any tier with *no*
allow-listed resources anywhere authorizes no resource-gated file.

Exclusion is unconditional and applied last: deny beats allow, including
over the channel's own explicit assignment.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import (
    ChannelConnectionExclusion,
    SharedConnection,
    SharedConnectionResource,
    SharedScope,
)
from app.models.team import Team


@dataclass
class AuthorizedConnection:
    connection: Connection
    resources: set[str] = field(default_factory=set)
    # Where this authorization comes from, for the UI ("inherited from Class").
    # If a connection is authorized at several tiers, the most specific wins
    # for display; resources still merge across all of them.
    source: str = "channel"  # "workspace" | "class" | "group" | "channel"


_SOURCE_RANK = {"workspace": 0, "class": 1, "group": 2, "channel": 3}


def _channel_lineage(session: Session, team_id: uuid.UUID) -> tuple[uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]:
    """(group_id, class_id, workspace_id) for a channel, or all None if the
    chain is broken. One query - the tree is shallow.

    The workspace comes from the Class rather than `Team.workspace_id` so the
    lineage is derived entirely through the hierarchy: a shared connection is
    matched against the workspace that actually owns this channel's class,
    never against a denormalized column that could disagree with the path.
    """
    row = session.execute(
        select(Team.group_id, Group.class_id, WorkspaceClass.workspace_id)
        .join(Group, Group.id == Team.group_id)
        .join(WorkspaceClass, WorkspaceClass.id == Group.class_id)
        .where(Team.id == team_id)
    ).first()
    if row is None:
        return None, None, None
    return row[0], row[1], row[2]


def _excluded_connection_ids(session: Session, team_id: uuid.UUID) -> set[uuid.UUID]:
    return set(session.execute(
        select(ChannelConnectionExclusion.connection_id).where(ChannelConnectionExclusion.team_id == team_id)
    ).scalars())


def authorized_connections(session: Session, team_id: uuid.UUID) -> dict[uuid.UUID, AuthorizedConnection]:
    """connection_id -> AuthorizedConnection, unioned across all four tiers,
    then narrowed by any channel exclusions."""
    group_id, class_id, workspace_id = _channel_lineage(session, team_id)
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

    # Broadest tier first, most specific last, so `source` ends up naming the
    # closest place the authorization came from.
    if workspace_id is not None:
        for sc, connection in _shared_rows(session, SharedScope.WORKSPACE, workspace_id):
            merge(connection, _shared_resource_keys(session, sc.id), "workspace")
    if class_id is not None:
        for sc, connection in _shared_rows(session, SharedScope.CLASS, class_id):
            merge(connection, _shared_resource_keys(session, sc.id), "class")
    if group_id is not None:
        for sc, connection in _shared_rows(session, SharedScope.GROUP, group_id):
            merge(connection, _shared_resource_keys(session, sc.id), "group")
    for cc, connection in _channel_rows(session, team_id):
        merge(connection, _channel_resource_keys(session, cc.id), "channel")

    # Narrowing pass, last and unconditional: deny beats allow. An excluded
    # connection leaves the authorized set no matter which tier granted it -
    # including this channel's own explicit assignment - so an admin can lock
    # one channel down without unsharing from everyone else, and two opposite
    # intentions always resolve to the safe reading.
    for connection_id in _excluded_connection_ids(session, team_id):
        result.pop(connection_id, None)

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
