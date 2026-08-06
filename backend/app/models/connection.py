import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Enum, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class Provider(str, enum.Enum):
    GITHUB = "github"
    GOOGLE_CALENDAR = "google_calendar"
    GMAIL = "gmail"
    GOOGLE_DRIVE = "google_drive"
    SLACK = "slack"
    # Microsoft 365 - one Entra ID grant fans out into these child services
    # (Sprint 1: mail + calendar), the structural twin of the Google grant.
    MICROSOFT_OUTLOOK_MAIL = "microsoft_outlook_mail"
    MICROSOFT_OUTLOOK_CALENDAR = "microsoft_outlook_calendar"


class ResourcePriority(str, enum.Enum):
    """How much a monitored resource matters, set by a person.

    This is the *context* that turns raw activity into operational meaning.
    "This repository has gone quiet" is not a finding on its own - most quiet
    repositories are simply finished or dormant, and alerting on all of them
    is noise. The same silence on a repository a human marked CRITICAL is a
    real risk, because the human supplied the judgment the data cannot.

    So classification does not describe the resource; it declares how Sentinel
    should reason about it. Only CRITICAL makes silence worth surfacing; the
    others are progressively quieter, and ARCHIVED/EXPERIMENTAL opt out of
    activity-based attention entirely. The field is provider-agnostic on
    purpose - the same five levels will weight a Jira project or a Slack
    channel when those arrive.
    """

    CRITICAL = "critical"
    NORMAL = "normal"
    LOW = "low"
    ARCHIVED = "archived"
    EXPERIMENTAL = "experimental"


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
    # One connection per (person, provider, resource) per workspace. `repo` is
    # part of the key so one GitHub *account* can monitor several
    # repositories, each its own row - which is what lets a repo flow through
    # the whole pipeline independently: it can be shared to one channel and
    # not another, excluded, investigated and attention-gated on its own,
    # because every downstream system already keys on connection_id.
    #
    # The key was (workspace, user, provider) before multi-repo. Google is
    # unaffected: its three services are distinct Provider values, and each
    # keeps repo as a fixed label ("gmail"/"calendar"/"drive"), so their rows
    # stay unique under the wider key exactly as before.
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "provider", "repo", name="uq_connection_workspace_user_provider_repo"),
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

    # A person can silence a monitored repository without disconnecting it -
    # keep the connection and its history, just stop syncing and stop it
    # producing attention. Distinct from revoked (the token still works) and
    # from deleted (the choice to watch it stands). Ingestion and the poll
    # skip a paused connection; readiness reports it as paused, not broken.
    # The GitHub account that authorized this, stored redundantly on each of
    # that account's repo rows. `org` holds a repo's *owner* (often an
    # organization the user only collaborates in), so it cannot double as the
    # account identity - without this, a user re-authorizing with a different
    # GitHub account could not be told apart from reconnecting the same one,
    # and the old account's repositories would be silently attributed to the
    # new token. NULL for non-GitHub providers.
    github_login: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # A human name for the resource, when its identifier is not one. `repo`
    # holds a Slack channel's *id* (stable across renames, what the API needs),
    # so the channel's name lives here for display. NULL where the identifier
    # already reads well (a GitHub repo, a Gmail label) - full_name falls back
    # to org/repo then. Generic on purpose: the next provider whose ids are not
    # human-readable uses the same field rather than inventing its own.
    display_name: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # How much this resource matters, as a person judged it. Drives whether
    # activity-based attention (a critical repo gone silent) fires at all -
    # see services/github_attention.py. NORMAL for everything until set.
    priority: Mapped[ResourcePriority] = mapped_column(
        Enum(ResourcePriority, name="resource_priority"), nullable=False, default=ResourcePriority.NORMAL,
        server_default=ResourcePriority.NORMAL.value,
    )

    paused_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # When the most recent sync actually succeeded, as opposed to last_synced_at
    # which advances even on a sync that fetched nothing. "Last successful" is
    # the honest health signal a user reads to trust a connection.
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Observability for the last ingestion run - what a person reads to trust a
    # sync: {ok, signals, messages_scanned, duration_ms, at, error}. Generic
    # (every provider's ingestion stamps it), written by ingest_connection on
    # both success and failure. NULL until a connection has synced once.
    last_sync_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    signals: Mapped[list["Signal"]] = relationship(back_populates="connection", cascade="all, delete-orphan")

    @property
    def full_name(self) -> str:
        # A resource's human name wins when it has one (a Slack channel), so the
        # rest of the app - attention titles, situations, the assistant - reads
        # "#all-sentinel" rather than a channel id.
        if self.display_name:
            return self.display_name
        if self.provider == Provider.GITHUB:
            return f"{self.org}/{self.repo}"
        return self.org
