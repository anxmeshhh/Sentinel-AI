import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint, Uuid
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
    # One account per person per provider per workspace. The database
    # enforces this so a race between two browser tabs can't recreate the
    # duplicate-connection problem the ownership change exists to fix.
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "provider", name="uq_connection_workspace_user_provider"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)

    # Whose account this is. Added in Phase 2x: connections used to be
    # keyed by (workspace, provider) alone, which silently meant "one
    # Google account per workspace". In a shared team workspace that was
    # data loss, not just a limitation - the second member to connect
    # replaced the first member's connection and purged their synced
    # signals, verified reproducibly before this change.
    #
    # An OAuth token is a delegation of one person's access, so it belongs
    # to that person. A team workspace now holds one connection per member
    # per provider, and each member's data stays theirs.
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

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

    # Set when Google refuses to mint a new access token (revoked consent,
    # expired refresh_token, password change). Phase 2x-B needs this because
    # expiry is otherwise *unobservable*: the stored `expires_at` only
    # describes the short-lived access token, which is refreshed silently, so
    # reading it would report every healthy connection as expired within the
    # hour. The only honest signal is a refresh that actually failed - so
    # that's what gets recorded. Cleared on a successful reconnect.
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    signals: Mapped[list["Signal"]] = relationship(back_populates="connection", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        if self.provider == Provider.GITHUB:
            return f"{self.org}/{self.repo}"
        return self.org
