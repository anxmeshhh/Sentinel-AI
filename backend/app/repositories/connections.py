from app.models.connection import Connection, Provider
from app.repositories.base import WorkspaceScopedRepository


class ConnectionRepository(WorkspaceScopedRepository[Connection]):
    model = Connection

    def list_all(self) -> list[Connection]:
        return list(self.session.execute(self._scoped()).scalars().all())

    def get_by_provider(self, provider: Provider) -> Connection | None:
        # Newest-first, deterministically. One connection per provider per
        # workspace is the design (the Google callback enforces it now),
        # but if duplicates ever exist again, unordered .first() let the DB
        # pick arbitrarily - confirmed real when two Google accounts were
        # briefly connected at once and fetches randomly used either token.
        return self.session.execute(
            self._scoped().where(Connection.provider == provider).order_by(Connection.created_at.desc())
        ).scalars().first()

    def mark_synced(self, connection: Connection, synced_at) -> None:
        connection.last_synced_at = synced_at
        self.session.add(connection)
