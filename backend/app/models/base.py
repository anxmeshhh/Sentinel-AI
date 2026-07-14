import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """DateTime that is always timezone-aware UTC on the Python side,
    regardless of backend.

    Postgres's `timestamptz` preserves tzinfo on its own; MySQL's `DATETIME`
    does not - it silently returns naive datetimes on read, which breaks any
    comparison against `datetime.now(timezone.utc)` (e.g. every agent's
    "signals from the last N days" windowing). Centralizing the fix here
    means every model gets correct, comparable datetimes without each
    caller having to remember to re-attach tzinfo.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class UUIDPk:
    # sqlalchemy.Uuid is backend-agnostic: native UUID on Postgres, CHAR(32) on
    # MySQL/SQLite. Using it (instead of the postgres-only dialect type) is
    # what let this move from Postgres to MySQL without touching every model.
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
