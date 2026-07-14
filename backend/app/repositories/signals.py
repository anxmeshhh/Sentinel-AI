import uuid
from datetime import datetime

from sqlalchemy.dialects.mysql import insert

from app.models.signal import Signal, SignalType
from app.repositories.base import WorkspaceScopedRepository


class SignalRepository(WorkspaceScopedRepository[Signal]):
    model = Signal

    def upsert(
        self,
        *,
        connection_id: uuid.UUID,
        type: SignalType,
        external_id: str,
        actor: str,
        payload: dict,
        occurred_at: datetime,
    ) -> None:
        """Idempotent write keyed on (connection_id, type, external_id).

        A retried/duplicated ingestion poll must never create duplicate
        signals - this is what makes ingestion safely resumable after a
        partial failure (see PRD SS7 reliability requirement).

        Uses MySQL's `INSERT ... ON DUPLICATE KEY UPDATE`, which fires off
        the same (connection_id, type, external_id) unique constraint as
        Postgres's ON CONFLICT would - MySQL just doesn't let you name the
        constraint explicitly, it infers it from the key that collided.
        """
        stmt = insert(Signal).values(
            workspace_id=self.workspace_id,
            connection_id=connection_id,
            type=type,
            external_id=external_id,
            actor=actor,
            payload=payload,
            occurred_at=occurred_at,
        )
        stmt = stmt.on_duplicate_key_update(payload=stmt.inserted.payload, actor=stmt.inserted.actor)
        self.session.execute(stmt)

    def since(self, connection_id: uuid.UUID, since: datetime) -> list[Signal]:
        rows = self._scoped().where(
            Signal.connection_id == connection_id,
            Signal.occurred_at >= since,
        )
        return list(self.session.execute(rows).scalars().all())
