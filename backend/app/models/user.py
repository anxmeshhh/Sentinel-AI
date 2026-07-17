"""Identity model, extended in the auth pass to support real signup/login:
email+password, OTP-verified email, and Google/Microsoft OAuth.

`hashed_password` is nullable because an OAuth-only user never sets one.
`google_sub`/`microsoft_sub` are the provider's stable subject id (not the
email) - the correct thing to match an OAuth login against, since a user's
email at the provider can change but their subject id never does.
"""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPk


class User(Base, UUIDPk, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    microsoft_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
