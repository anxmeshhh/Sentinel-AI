"""Zoom OAuth: the code exchange, and keeping a connection's token valid.

Driven manually rather than through authlib, for the same reason Slack is: Zoom
authenticates the *token request itself* with HTTP Basic
(`Base64(client_id:client_secret)`) rather than posting the credentials as form
fields, and it is not an OpenID provider so there is no discovery document to
register against. An explicit exchange is clearer than bending authlib to it.

Two Zoom-specific facts drive the refresh logic:

  * Access tokens last one hour - the same cadence as Google and Microsoft.
  * The refresh token ROTATES on every refresh, and the old one dies
    immediately. This is the Microsoft behaviour, not the Google one, so the
    new token MUST be persisted or the connection becomes unrefreshable after a
    single cycle. Zoom's own docs put it plainly: always use the latest refresh
    token for the next request.

Refresh tokens also expire after 90 days of no use, which is why a failed
refresh stamps `revoked_at`: that is the one honest, observable signal that the
grant is dead and the person has to reconnect. Same contract as every other
OAuth provider here, so connection_state() needs no Zoom branch.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_token, encrypt_token
from app.models.connection import Connection

logger = structlog.get_logger("sentinel.zoom_auth")

AUTHORIZE_URL = "https://zoom.us/oauth/authorize"
TOKEN_URL = "https://zoom.us/oauth/token"
REFRESH_BUFFER = timedelta(minutes=5)

# What a fresh connection asks for, in Zoom's GRANULAR scope format (the classic
# `meeting:read` style was superseded; a granular app rejects the old names).
#
# Least privilege, and every entry is here because something concrete needs it:
#   user:read:user                    /users/me, for the account identity + plan
#   meeting:read:list_meetings        the ingestion list
#   meeting:read:meeting              detail: agenda, join url, settings
#   meeting:write:meeting             create
#   meeting:update:meeting            update
#   meeting:delete:meeting            delete
#   meeting:read:list_past_participants  who actually attended (plan-gated)
#   cloud_recording:read:list_user_recordings  recordings list (plan-gated)
#   cloud_recording:read:list_recording_files  a meeting's files, incl. transcript
#
# The last three are requested but may not be GRANTED (an account without the
# plan cannot consent to what it does not have). Nothing here assumes they
# worked - services/zoom_capabilities.py asks Zoom what actually functions.
SCOPES = " ".join((
    "user:read:user",
    "meeting:read:list_meetings",
    "meeting:read:meeting",
    "meeting:write:meeting",
    "meeting:update:meeting",
    "meeting:delete:meeting",
    "meeting:read:list_past_participants",
    "cloud_recording:read:list_user_recordings",
    "cloud_recording:read:list_recording_files",
))


class ZoomAuthError(Exception):
    pass


def _basic_header() -> dict[str, str]:
    settings = get_settings()
    raw = f"{settings.zoom_client_id}:{settings.zoom_client_secret}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


def authorize_url(redirect_uri: str, state: str) -> str:
    """Where the browser is sent to consent. `state` carries the connect ticket
    so the callback can prove which user and workspace this belongs to."""
    from urllib.parse import urlencode

    settings = get_settings()
    query = urlencode({
        "response_type": "code",
        "client_id": settings.zoom_client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        # Zoom applies the app's configured scopes; sending them explicitly
        # keeps the request self-describing and matches what the app declares.
        "scope": SCOPES,
    })
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Authorization code -> token blob. Raises ZoomAuthError with Zoom's own
    message, which is worth surfacing: a redirect_uri mismatch is the single
    most common setup failure and Zoom names it precisely."""
    response = httpx.post(
        TOKEN_URL,
        headers=_basic_header(),
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        timeout=20.0,
    )
    if response.status_code != 200:
        logger.warning("zoom_code_exchange_failed", status=response.status_code, body=response.text[:300])
        raise ZoomAuthError(f"Zoom rejected the authorization code: {response.text[:200]}")
    return response.json()


def token_blob(token: dict) -> str:
    """The encrypted-at-rest shape every OAuth provider here stores."""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token.get("expires_in", 3600))
    return encrypt_token(json.dumps({
        "access_token": token["access_token"],
        "refresh_token": token["refresh_token"],
        "expires_at": expires_at.isoformat(),
    }))


def get_valid_access_token(session: Session, connection: Connection) -> str:
    """A currently-valid access token, refreshing and persisting a new one -
    including the ROTATED refresh token - when the stored one is near expiry."""
    blob = json.loads(decrypt_token(connection.encrypted_token))
    expires_at = datetime.fromisoformat(blob["expires_at"])

    if datetime.now(timezone.utc) < expires_at - REFRESH_BUFFER:
        return blob["access_token"]

    response = httpx.post(
        TOKEN_URL,
        headers=_basic_header(),
        data={"grant_type": "refresh_token", "refresh_token": blob["refresh_token"]},
        timeout=20.0,
    )
    if response.status_code != 200:
        # A refresh token that expired (90 days) or was revoked in Zoom's app
        # settings lands here. Recording it is what lets the connection report
        # `token_revoked` honestly instead of looking like an empty sync.
        connection.revoked_at = datetime.now(timezone.utc)
        session.add(connection)
        session.commit()
        logger.warning("zoom_token_refresh_failed", connection_id=str(connection.id), status=response.status_code)
        raise ZoomAuthError(f"Zoom token refresh failed: {response.status_code}")

    data = response.json()
    connection.encrypted_token = encrypt_token(json.dumps({
        "access_token": data["access_token"],
        # Rotation: Zoom issues a new refresh token and invalidates the old one.
        # Falling back to the previous value would be wrong if Zoom ever omitted
        # it, but keeping SOMETHING beats storing null and losing refresh forever.
        "refresh_token": data.get("refresh_token", blob["refresh_token"]),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))).isoformat(),
    }))
    session.add(connection)
    session.commit()

    logger.info("zoom_token_refreshed", connection_id=str(connection.id))
    return data["access_token"]


def fetch_account_identity(access_token: str) -> str:
    """The connected Zoom account's email, used as Connection.org - the same
    role the Google/Microsoft account identity plays."""
    response = httpx.get(
        "https://api.zoom.us/v2/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20.0,
    )
    if response.status_code != 200:
        raise ZoomAuthError(f"Could not read the Zoom account: {response.status_code}")
    data = response.json()
    return data.get("email") or data.get("id") or "unknown"
