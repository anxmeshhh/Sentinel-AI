"""Google Calendar/Gmail "Connect" flow.

Distinct from /auth/google/* (login): that flow only ever needs an id_token
to identify a user and nothing is stored. This flow requests broader,
offline-access scopes and stores the resulting access+refresh token pair as
Connections, the same shape GitHub connections already use.

Full-page OAuth redirects can't carry an Authorization header (a browser
navigation never sends custom headers), so this uses a short-lived
"connect ticket" instead of the real session JWT - see core/auth.py's
create_connect_ticket/decode_connect_ticket docstring for the full reasoning.
"""

import json
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.core.auth import InvalidTokenError, create_connect_ticket, decode_connect_ticket
from app.core.config import get_settings
from app.core.oauth import GOOGLE_CONFIGURED, oauth
from app.core.security import encrypt_token
from app.models.connection import Connection, Provider
from app.models.user import User
from app.schemas.integration import ConnectTicketOut

router = APIRouter(prefix="/integrations", tags=["integrations"])

GOOGLE_CONNECT_PURPOSE = "google_connect"


@router.post("/google/connect-ticket", response_model=ConnectTicketOut)
def create_google_connect_ticket(
    user: User = Depends(get_current_user),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> ConnectTicketOut:
    """Step 1 of the connect flow: an authenticated fetch() call (same
    X-Workspace-Id-scoped pattern every other route uses), which *can* carry
    the real Authorization header, exchanges it for a ticket that's safe to
    put in a URL for step 2's full-page redirect.
    """
    if not GOOGLE_CONFIGURED:
        raise HTTPException(status_code=501, detail="Google integration is not configured yet")
    ticket = create_connect_ticket(user_id=user.id, workspace_id=workspace_id, purpose=GOOGLE_CONNECT_PURPOSE)
    return ConnectTicketOut(ticket=ticket)


@router.get("/google/connect")
async def google_connect(request: Request, ticket: str):
    if not GOOGLE_CONFIGURED:
        raise HTTPException(status_code=501, detail="Google integration is not configured yet")
    try:
        user_id, workspace_id = decode_connect_ticket(ticket, expected_purpose=GOOGLE_CONNECT_PURPOSE)
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="This connect link is invalid or has expired - try again")

    # Stashed in the OAuth dance's own session (already used for state/nonce,
    # see main.py's SessionMiddleware) - read back in the callback below.
    request.session["google_connect_user_id"] = str(user_id)
    request.session["google_connect_workspace_id"] = str(workspace_id)

    redirect_uri = f"{get_settings().backend_base_url}/integrations/google/callback"
    # access_type=offline is what makes Google issue a refresh_token at all -
    # verified directly that client_kwargs at registration time (core/oauth.py)
    # does NOT reliably propagate this one through to the actual redirect URL
    # (prompt did, access_type didn't), so it's passed explicitly here instead.
    return await oauth.google_data.authorize_redirect(request, redirect_uri, access_type="offline", prompt="consent")


@router.get("/google/callback")
async def google_connect_callback(request: Request, session: Session = Depends(get_db)):
    if not GOOGLE_CONFIGURED:
        raise HTTPException(status_code=501, detail="Google integration is not configured yet")

    workspace_id_str = request.session.pop("google_connect_workspace_id", None)
    request.session.pop("google_connect_user_id", None)
    if not workspace_id_str:
        return RedirectResponse(f"{get_settings().frontend_base_url}/?google_error=session_expired")

    token = await oauth.google_data.authorize_access_token(request)
    access_token = token["access_token"]
    refresh_token = token.get("refresh_token")
    userinfo = token.get("userinfo") or {}
    google_email = userinfo.get("email") or "unknown-google-account"

    if not refresh_token:
        # Google only issues a refresh_token on first consent (or when
        # prompt=consent forces re-consent, which we always request) - if
        # it's still missing, something's off with the app's OAuth config
        # rather than anything the user did wrong.
        return RedirectResponse(f"{get_settings().frontend_base_url}/?google_error=no_refresh_token")

    expires_at_ts = token.get("expires_at") or (time.time() + token.get("expires_in", 3600))
    expires_at = datetime.fromtimestamp(expires_at_ts, tz=timezone.utc)

    encrypted = encrypt_token(
        json.dumps({"access_token": access_token, "refresh_token": refresh_token, "expires_at": expires_at.isoformat()})
    )

    workspace_id = uuid.UUID(workspace_id_str)
    for provider, label in [(Provider.GOOGLE_CALENDAR, "calendar"), (Provider.GMAIL, "gmail")]:
        existing = session.execute(
            select(Connection).where(
                Connection.workspace_id == workspace_id, Connection.provider == provider, Connection.org == google_email
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.encrypted_token = encrypted
        else:
            session.add(
                Connection(workspace_id=workspace_id, provider=provider, org=google_email, repo=label, encrypted_token=encrypted)
            )
    session.commit()

    return RedirectResponse(f"{get_settings().frontend_base_url}/?connected=google")
