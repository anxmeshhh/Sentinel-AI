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
