import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class Provider(str, enum.Enum):
    GITHUB = "github"
    GOOGLE_CALENDAR = "google_calendar"
    GMAIL = "gmail"
    GOOGLE_DRIVE = "google_drive"


class Connection(Base, UUIDPk, TimestampMixin):
    """A workspace's authorization to read one external system.

    `org`/`repo` are reused (not renamed, to avoid a risky migration on a
    working GitHub integration) as generic identifying fields per provider:
    - GitHub: org="northwind", repo="checkout-service" -> "northwind/checkout-service"
    - Google Calendar/Gmail: org=the connected Google account's email,
      repo="calendar"|"gmail" (a fixed label, not a second identifier)
    `full_name` renders the right thing for either shape.
    """

    __tablename__ = "connections"

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    provider: Mapped[Provider] = mapped_column(Enum(Provider, name="connection_provider"), nullable=False)
    org: Mapped[str] = mapped_column(String(200), nullable=False)
    repo: Mapped[str] = mapped_column(String(200), nullable=False)

    # Fernet-encrypted at rest; see app.core.security. Never logged, never serialized in API responses.
    # Text, not VARCHAR(n): MySQL requires an explicit length for VARCHAR, and
    # ciphertext length isn't worth bounding precisely. For Google providers
    # this holds an encrypted JSON blob {access_token, refresh_token,
    # expires_at}, not a single PAT string - decrypt_token() only reverses
    # the Fernet layer, callers are responsible for (de)serializing the JSON.
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)

    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    signals: Mapped[list["Signal"]] = relationship(back_populates="connection", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        if self.provider == Provider.GITHUB:
            return f"{self.org}/{self.repo}"
        return self.org
