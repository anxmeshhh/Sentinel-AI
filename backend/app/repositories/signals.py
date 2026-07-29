import json
import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

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

        Dialect-aware so ingestion is exercisable on SQLite in tests, not only
        against MySQL in production. Both express the same intent - insert, or
        on a collision of the (connection_id, type, external_id) unique key,
        refresh the mutable fields - MySQL via ON DUPLICATE KEY UPDATE (which
        infers the key), SQLite via ON CONFLICT naming it explicitly.
        """
        values = dict(
            workspace_id=self.workspace_id,
            connection_id=connection_id,
            type=type,
            external_id=external_id,
            actor=actor,
            payload=payload,
            occurred_at=occurred_at,
        )
        if self.session.bind.dialect.name == "sqlite":
            stmt = sqlite_insert(Signal).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["connection_id", "type", "external_id"],
                set_={"payload": stmt.excluded.payload, "actor": stmt.excluded.actor},
            )
        else:
            stmt = mysql_insert(Signal).values(**values)
            stmt = stmt.on_duplicate_key_update(payload=stmt.inserted.payload, actor=stmt.inserted.actor)
        self.session.execute(stmt)

    def since(self, connection_id: uuid.UUID, since: datetime) -> list[Signal]:
        rows = self._scoped().where(
            Signal.connection_id == connection_id,
            Signal.occurred_at >= since,
        )
        return list(self.session.execute(rows).scalars().all())

    # ---- Gmail/Calendar structured browsing (Google module) ----
    #
    # Gmail label membership (STARRED, IMPORTANT, SPAM, UNREAD, CATEGORY_*)
    # already lives in payload.label_ids for every ingested EMAIL signal -
    # no schema change needed, just a MySQL JSON_CONTAINS check per label.

    def _has_label(self, label: str):
        return func.json_contains(Signal.payload, json.dumps(label), "$.label_ids") == 1

    def list_mail(
        self,
        *,
        labels_any: list[str] | None = None,
        exclude_labels: list[str] | None = None,
        limit: int = 30,
    ) -> list[Signal]:
        query = self._scoped().where(Signal.type == SignalType.EMAIL)
        if labels_any:
            query = query.where(or_(*[self._has_label(label) for label in labels_any]))
        for label in exclude_labels or []:
            query = query.where(~self._has_label(label))
        query = query.order_by(Signal.occurred_at.desc()).limit(limit)
        return list(self.session.execute(query).scalars().all())

    def count_mail(self, *, labels_any: list[str] | None = None, exclude_labels: list[str] | None = None) -> int:
        query = select(func.count()).select_from(Signal).where(
            Signal.workspace_id == self.workspace_id, Signal.type == SignalType.EMAIL
        )
        if labels_any:
            query = query.where(or_(*[self._has_label(label) for label in labels_any]))
        for label in exclude_labels or []:
            query = query.where(~self._has_label(label))
        return self.session.execute(query).scalar_one()

    def list_calendar(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        ascending: bool = True,
        limit: int = 30,
    ) -> list[Signal]:
        query = self._scoped().where(Signal.type == SignalType.CALENDAR_EVENT)
        if since is not None:
            query = query.where(Signal.occurred_at >= since)
        if until is not None:
            query = query.where(Signal.occurred_at <= until)
        query = query.order_by(Signal.occurred_at.asc() if ascending else Signal.occurred_at.desc()).limit(limit)
        return list(self.session.execute(query).scalars().all())
