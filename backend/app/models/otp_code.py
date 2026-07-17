"""One-time codes for email verification and passwordless login.

Only the hash of the code is stored (same discipline as password hashing -
a DB read should never reveal a usable code). `attempts` caps brute-force
guessing of a 6-digit code within its short expiry window.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, UUIDPk


class OtpPurpose(str, enum.Enum):
    EMAIL_VERIFY = "email_verify"
    LOGIN = "login"


class OtpCode(Base, UUIDPk, TimestampMixin):
    __tablename__ = "otp_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    purpose: Mapped[OtpPurpose] = mapped_column(Enum(OtpPurpose, name="otp_purpose"), nullable=False)

    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
