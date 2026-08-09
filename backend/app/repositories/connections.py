import uuid

from app.models.connection import Connection, Provider
from app.repositories.base import WorkspaceScopedRepository


class ConnectionRepository(WorkspaceScopedRepository[Connection]):
    model = Connection

    def list_all(self) -> list[Connection]:
        """Every connection in the workspace, regardless of owner.

        Only appropriate for admin/config surfaces that need to see what
        exists. Anything acting on a user's behalf must go through
        `get_for_user` instead, or it risks reading someone else's mailbox.
        """
        return list(self.session.execute(self._scoped()).scalars().all())

    def list_for_user(self, user_id: uuid.UUID) -> list[Connection]:
        return list(
            self.session.execute(self._scoped().where(Connection.user_id == user_id)).scalars().all()
        )

    def get_for_user(self, user_id: uuid.UUID, provider: Provider) -> Connection | None:
        """The connection Sentinel may use when acting for this person.

        Connections are per-user as of Phase 2x: an OAuth token delegates
        one individual's access, so retrieval must name whose access is
        being exercised. There is no workspace-wide fallback on purpose -
        silently borrowing a teammate's token is exactly the leak this
        model exists to prevent.
        """
        return self.session.execute(
            self._scoped().where(Connection.provider == provider, Connection.user_id == user_id)
        ).scalars().first()

    def mark_synced(self, connection: Connection, synced_at) -> None:
        connection.last_synced_at = synced_at
        self.session.add(connection)

    def disconnect(self, connection: Connection) -> None:
        """Remove a connection and everything that depends on it.

        Deleting the row on its own fails: six tables carry a foreign key to
        connections, and two of those have children of their own. Only
        `signals` had an ORM cascade, so the other five raised IntegrityError -
        found by deleting a real connection, which failed twice before the whole
        graph was mapped.

        Each child is handled by what it MEANS, not by what makes the delete
        succeed:

          signals                 gone. They describe a source that can no
                                  longer be read - the same reasoning
                                  provision_grant already uses when a different
                                  account signs in.
          attention_items         gone. A live "act on this" item pointing at a
                                  disconnected provider is worse than absent.
          channel_connections     gone, with their resources. These are
          shared_connections      authorization grants; leaving them would keep
          ..._exclusions          a channel authorized for something that no
                                  longer exists.
          agent_runs              KEPT, detached (connection_id -> NULL). These
                                  are historical runs with briefs a person may
                                  have read. The column is nullable precisely so
                                  history can outlive its source, and silently
                                  deleting something a user read is a worse
                                  surprise than an orphaned record.
        """
        from sqlalchemy import delete, select, update

        from app.models.agent_run import AgentRun
        from app.models.attention_item import AttentionItem
        from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
        from app.models.shared_connection import (
            ChannelConnectionExclusion,
            SharedConnection,
            SharedConnectionResource,
        )

        cid = connection.id

        # Grandchildren first - each parent's own children, then the parent.
        channel_ids = self.session.execute(
            select(ChannelConnection.id).where(ChannelConnection.connection_id == cid)
        ).scalars().all()
        if channel_ids:
            self.session.execute(
                delete(ChannelConnectionResource).where(
                    ChannelConnectionResource.channel_connection_id.in_(channel_ids)
                )
            )
        shared_ids = self.session.execute(
            select(SharedConnection.id).where(SharedConnection.connection_id == cid)
        ).scalars().all()
        if shared_ids:
            self.session.execute(
                delete(SharedConnectionResource).where(
                    SharedConnectionResource.shared_connection_id.in_(shared_ids)
                )
            )

        self.session.execute(delete(ChannelConnection).where(ChannelConnection.connection_id == cid))
        self.session.execute(delete(SharedConnection).where(SharedConnection.connection_id == cid))
        self.session.execute(
            delete(ChannelConnectionExclusion).where(ChannelConnectionExclusion.connection_id == cid)
        )
        self.session.execute(delete(AttentionItem).where(AttentionItem.connection_id == cid))
        # Detached rather than deleted - see the docstring.
        self.session.execute(
            update(AgentRun).where(AgentRun.connection_id == cid).values(connection_id=None)
        )

        # Signals go with the ORM cascade already declared on the relationship.
        self.session.delete(connection)
        self.session.commit()
