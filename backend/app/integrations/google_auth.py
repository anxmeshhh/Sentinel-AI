"""Keeps a Google Connection's stored access token valid.

Google access tokens expire in ~1h; the refresh_token (stored once, at
connect time - see api/routes/integrations.py) is long-lived and used here
to mint new access tokens without ever asking the user to re-consent.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_token, encrypt_token
from app.models.connection import Connection

logger = structlog.get_logger("sentinel.google_auth")

TOKEN_URL = "https://oauth2.googleapis.com/token"
REFRESH_BUFFER = timedelta(minutes=5)  # refresh a little before actual expiry, not right at the edge


class GoogleAuthError(Exception):
    pass


def get_valid_access_token(session: Session, connection: Connection) -> str:
    """Returns a currently-valid access token for this connection, refreshing
    and persisting a new one first if the stored one is expired or close to it.
    """
    blob = json.loads(decrypt_token(connection.encrypted_token))
    expires_at = datetime.fromisoformat(blob["expires_at"])

    if datetime.now(timezone.utc) < expires_at - REFRESH_BUFFER:
        return blob["access_token"]

    settings = get_settings()
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": blob["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=20.0,
    )
    if response.status_code != 200:
        # A revoked/expired refresh_token ends up here - the connection needs
        # to be reconnected by the user, not silently retried forever.
        logger.warning("google_token_refresh_failed", connection_id=str(connection.id), status=response.status_code)
        raise GoogleAuthError(f"Google token refresh failed: {response.status_code}")

    data = response.json()
    new_access_token = data["access_token"]
    new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))

    connection.encrypted_token = encrypt_token(
        json.dumps({"access_token": new_access_token, "refresh_token": blob["refresh_token"], "expires_at": new_expires_at.isoformat()})
    )
    session.add(connection)
    session.commit()

    logger.info("google_token_refreshed", connection_id=str(connection.id))
    return new_access_token
