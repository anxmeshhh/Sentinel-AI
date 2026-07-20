"""Identity model, extended in the auth pass to support real signup/login:
email+password, OTP-verified email, and Google/Microsoft OAuth.

`hashed_password` is nullable because an OAuth-only user never sets one.
`google_sub`/`microsoft_sub` are the provider's stable subject id (not the
email) - the correct thing to match an OAuth login against, since a user's
email at the provider can change but their subject id never does.
"""

import enum
from datetime import datetime  # noqa: TC003 - used in a Mapped annotation

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class Persona(str, enum.Enum):
    """Phase 2r: "How do you work?" - a *configuration* of one platform,
    never a fork (see the product principle: same engine, different
    Connections). Persona only influences which connections are suggested
    and which surfaces are emphasized; every capability remains reachable
    for every persona.
    """

    INDIVIDUAL = "individual"  # professional: mail/calendar/meetings/docs
    DEVELOPER = "developer"  # + code hosting, issues, PR/sprint attention
    TEAM = "team"  # startup/small team: Groups, Channels, shared connections
    BUSINESS = "business"  # organization: departments, RBAC, admin controls
    EXPLORER = "explorer"  # demo-only: seeded workspace, no real accounts connected


class User(Base, UUIDPk, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    microsoft_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)

    # Nullable = never onboarded; the frontend shows the persona picker until
    # onboarded_at is set. Kept on User (not Workspace) because "how I work"
    # is a property of the person, not of any one workspace they belong to.
    persona: Mapped[Persona | None] = mapped_column(Enum(Persona, name="user_persona"), nullable=True)
    onboarded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
