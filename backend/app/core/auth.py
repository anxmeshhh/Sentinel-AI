"""Password hashing, session JWTs, and short-lived "connect tickets."

Kept separate from core/security.py (Fernet encryption of third-party
tokens like GitHub PATs) - this file is about proving who a Sentinel user
is, a different concern from protecting a third-party credential at rest.
"""

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings


def hash_secret(plaintext: str) -> str:
    """Used for both account passwords and OTP codes - same hashing
    discipline applies to both (never store either in a form usable as-is)."""
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def verify_secret(plaintext: str, hashed: str) -> bool:
    return bcrypt.checkpw(plaintext.encode(), hashed.encode())


class InvalidTokenError(Exception):
    pass


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.session_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> uuid.UUID:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.session_secret_key, algorithms=["HS256"])
        if "typ" in payload:
            # Defense in depth: a connect-ticket (below) must never work as a
            # session token even if it leaked somewhere a Bearer token would
            # be read from.
            raise InvalidTokenError("not a session token")
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc


CONNECT_TICKET_EXPIRE_MINUTES = 5


def create_connect_ticket(*, user_id: uuid.UUID, workspace_id: uuid.UUID, purpose: str) -> str:
    """Full-page OAuth redirects (Google Calendar/Gmail "Connect" flows)
    can't carry an Authorization header the way a fetch() call can - a
    browser navigation never sends custom headers. This is the standard fix:
    an authenticated API call first mints a short-lived, single-purpose
    ticket; that ticket (not the real session token) goes in the redirect
    URL, where it's safe to have expire in minutes and be scoped to exactly
    one action.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "typ": "connect_ticket",
        "purpose": purpose,
        "sub": str(user_id),
        "workspace_id": str(workspace_id),
        "iat": now,
        "exp": now + timedelta(minutes=CONNECT_TICKET_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.session_secret_key, algorithm="HS256")


def decode_connect_ticket(token: str, *, expected_purpose: str) -> tuple[uuid.UUID, uuid.UUID]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.session_secret_key, algorithms=["HS256"])
        if payload.get("typ") != "connect_ticket" or payload.get("purpose") != expected_purpose:
            raise InvalidTokenError("wrong ticket type or purpose")
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["workspace_id"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc
