"""Signup, login, and OTP business logic.

Not workspace-scoped (unlike most of this codebase's services) - a User
account exists above and independent of any workspace, per IA.md's "one
account, many workspaces" model.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import hash_secret, verify_secret
from app.core.bootstrap import provision_personal_workspace_for_user
from app.core.config import get_settings
from app.core.email import get_email_sender
from app.models.otp_code import OtpCode, OtpPurpose
from app.models.user import User

logger = structlog.get_logger("sentinel.auth")


class AuthError(Exception):
    """Raised for any user-facing auth failure - routes translate this to a
    generic 400/401 rather than leaking which specific check failed
    (e.g. "invalid email or password", never "no such user")."""


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.execute(select(User).where(User.email == email)).scalar_one_or_none()


def create_user_with_password(session: Session, *, email: str, name: str, password: str) -> User:
    if get_user_by_email(session, email) is not None:
        raise AuthError("An account with this email already exists")

    user = User(email=email, name=name, hashed_password=hash_secret(password), email_verified=False)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate_with_password(session: Session, *, email: str, password: str) -> User:
    user = get_user_by_email(session, email)
    if user is None or user.hashed_password is None or not verify_secret(password, user.hashed_password):
        raise AuthError("Invalid email or password")
    if not user.email_verified:
        raise AuthError("Email not verified - check for your verification code")
    return user


def find_or_create_oauth_user(session: Session, *, provider: str, sub: str, email: str, name: str) -> User:
    """provider is 'google' or 'microsoft'. Matches on the provider's stable
    subject id first (a user's email at the provider can change; their sub
    never does), falling back to linking an existing password account with
    the same email so a user isn't forced into two separate accounts."""
    sub_column = User.google_sub if provider == "google" else User.microsoft_sub
    user = session.execute(select(User).where(sub_column == sub)).scalar_one_or_none()
    if user is not None:
        return user

    user = get_user_by_email(session, email)
    if user is None:
        user = User(email=email, name=name, email_verified=True)
        session.add(user)
    else:
        user.email_verified = True  # the OAuth provider already verified this email

    if provider == "google":
        user.google_sub = sub
    else:
        user.microsoft_sub = sub

    session.commit()
    session.refresh(user)

    # Idempotent (checks for an existing workspace first) - always called
    # rather than gated on "is this a brand new user," so a user who created
    # a password account but never finished OTP verification, then signs in
    # with Google/Microsoft using the same email, still ends up with one.
    provision_personal_workspace_for_user(session, user)

    return user


def generate_and_send_otp(session: Session, *, user: User, purpose: OtpPurpose) -> None:
    settings = get_settings()
    code = "".join(secrets.choice("0123456789") for _ in range(settings.otp_length))

    otp = OtpCode(
        id=uuid.uuid4(),
        user_id=user.id,
        purpose=purpose,
        code_hash=hash_secret(code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes),
    )
    session.add(otp)
    session.commit()

    subject = "Your Sentinel verification code" if purpose == OtpPurpose.EMAIL_VERIFY else "Your Sentinel login code"
    get_email_sender().send(
        to=user.email,
        subject=subject,
        body=f"Your code is {code}. It expires in {settings.otp_expire_minutes} minutes.",
    )
    logger.info("otp_generated", user_id=str(user.id), purpose=purpose.value)


def verify_otp(session: Session, *, user: User, purpose: OtpPurpose, code: str) -> None:
    settings = get_settings()
    otp = session.execute(
        select(OtpCode)
        .where(OtpCode.user_id == user.id, OtpCode.purpose == purpose, OtpCode.consumed_at.is_(None))
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if otp is None:
        raise AuthError("No pending code - request a new one")
    if otp.expires_at < datetime.now(timezone.utc):
        raise AuthError("Code expired - request a new one")
    if otp.attempts >= settings.otp_max_attempts:
        raise AuthError("Too many incorrect attempts - request a new one")

    if not verify_secret(code, otp.code_hash):
        otp.attempts += 1
        session.commit()
        raise AuthError("Incorrect code")

    otp.consumed_at = datetime.now(timezone.utc)
    if purpose == OtpPurpose.EMAIL_VERIFY:
        user.email_verified = True
    session.commit()

    if purpose == OtpPurpose.EMAIL_VERIFY:
        provision_personal_workspace_for_user(session, user)
