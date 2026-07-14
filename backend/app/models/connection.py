import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class Provider(str, enum.Enum):
    GITHUB = "github"


class Connection(Base, UUIDPk, TimestampMixin):
    """A workspace's authorization to read one external system (e.g. one GitHub repo)."""

    __tablename__ = "connections"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    provider: Mapped[Provider] = mapped_column(Enum(Provider, name="connection_provider"), nullable=False)
    org: Mapped[str] = mapped_column(String(200), nullable=False)
    repo: Mapped[str] = mapped_column(String(200), nullable=False)

    # Fernet-encrypted at rest; see app.core.security. Never logged, never serialized in API responses.
    # Text, not VARCHAR(n): MySQL requires an explicit length for VARCHAR, and
    # ciphertext length isn't worth bounding precisely.
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)

    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    signals: Mapped[list["Signal"]] = relationship(back_populates="connection", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        return f"{self.org}/{self.repo}"
