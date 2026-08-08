"""Keeps a Microsoft 365 Connection's stored access token valid.

The twin of google_auth: Entra ID access tokens expire in ~1h and are refreshed
here from the long-lived refresh_token without re-consent. One difference that
matters - Microsoft ROTATES the refresh_token on every refresh, so the new one
in the response must be stored, not the old one (Google returns the same token
and omits it). Revocation is observable the same way: a failed refresh stamps
revoked_at, the one honest signal that the connection is dead.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_token, encrypt_token
from app.models.connection import Connection

logger = structlog.get_logger("sentinel.microsoft_auth")

# "common" lets both work/school (Entra) and personal Microsoft accounts sign in;
# a single-tenant app would substitute its tenant id here.
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
REFRESH_BUFFER = timedelta(minutes=5)
# The scopes this app asks for at CONSENT time, mirroring core/oauth.py's
# microsoft_data client. Deliberately NOT sent on refresh (see below) - it is
# documentation of what a fresh connection requests, not a refresh parameter.
# No openid/email: this app requests no ID token at all, see core/oauth.py.
# User.Read is what lets Graph's /me resolve the account identity.
SCOPES = "offline_access User.Read Mail.ReadWrite Mail.Send Calendars.ReadWrite Team.ReadBasic.All Channel.ReadBasic.All Files.ReadWrite Notes.ReadWrite Tasks.ReadWrite"


class MicrosoftAuthError(Exception):
    pass


def get_valid_access_token(session: Session, connection: Connection) -> str:
    """A currently-valid access token for this connection, refreshing and
    persisting a new one (including the rotated refresh_token) if needed."""
    blob = json.loads(decrypt_token(connection.encrypted_token))
    expires_at = datetime.fromisoformat(blob["expires_at"])

    if datetime.now(timezone.utc) < expires_at - REFRESH_BUFFER:
        return blob["access_token"]

    settings = get_settings()
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": settings.microsoft_client_id,
            "client_secret": settings.microsoft_client_secret,
            "refresh_token": blob["refresh_token"],
            "grant_type": "refresh_token",
            # NO "scope" here, deliberately. A refresh_token grant can only ever
            # return scopes that were actually consented to; asking for MORE
            # than that makes Entra reject the whole refresh with a 400, which
            # Sentinel then reads as a dead grant and stamps revoked_at.
            #
            # That is not hypothetical - it happened the moment Tasks.ReadWrite
            # was added: every existing connection's refresh started failing,
            # because SCOPES had grown past what the stored token covered.
            # Omitting it returns exactly the granted set, so adding a scope now
            # affects only the NEXT consent instead of breaking live connections.
        },
        timeout=20.0,
    )
    if response.status_code != 200:
        # A revoked/expired refresh_token ends up here: reconnect is required.
        # Record it - the only observable evidence the connection is dead, which
        # channel readiness reports as `expired` rather than guessing.
        connection.revoked_at = datetime.now(timezone.utc)
        session.add(connection)
        session.commit()
        logger.warning("microsoft_token_refresh_failed", connection_id=str(connection.id), status=response.status_code)
        raise MicrosoftAuthError(f"Microsoft token refresh failed: {response.status_code}")

    data = response.json()
    new_access_token = data["access_token"]
    # Rotation: Entra returns a fresh refresh_token; fall back to the old one
    # only if (unexpectedly) absent, so we never lose the ability to refresh.
    new_refresh_token = data.get("refresh_token", blob["refresh_token"])
    new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))

    connection.encrypted_token = encrypt_token(
        json.dumps({"access_token": new_access_token, "refresh_token": new_refresh_token, "expires_at": new_expires_at.isoformat()})
    )
    session.add(connection)
    session.commit()

    logger.info("microsoft_token_refreshed", connection_id=str(connection.id))
    return new_access_token
