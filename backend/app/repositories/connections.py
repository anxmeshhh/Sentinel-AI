from app.models.connection import Connection, Provider
from app.repositories.base import WorkspaceScopedRepository


class ConnectionRepository(WorkspaceScopedRepository[Connection]):
    model = Connection

    def list_all(self) -> list[Connection]:
        return list(self.session.execute(self._scoped()).scalars().all())

    def get_by_provider(self, provider: Provider) -> Connection | None:
        return self.session.execute(self._scoped().where(Connection.provider == provider)).scalars().first()

    def mark_synced(self, connection: Connection, synced_at) -> None:
        connection.last_synced_at = synced_at
        self.session.add(connection)
