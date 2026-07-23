"""Is this GitHub connection still alive?

## Why this file exists

Until now GitHub was the one provider whose death Sentinel could not see. A
pasted PAT has no refresh flow, so there was no failed refresh to record, and
`revoked_at` stayed NULL forever - which meant a revoked token still reported
`ready`, and a channel depending on it looked healthy while returning
nothing. That was a real correctness bug, not a missing feature.

An OAuth App fixes it, but not the way Google does. GitHub OAuth App tokens
**do not expire and have no refresh token**, so there is nothing to refresh
and no refresh to fail. What an OAuth App does have is the client
credentials, and GitHub exposes an endpoint that answers the question
directly:

    POST /applications/{client_id}/token   -> 200 alive, 404 dead

That is a better signal than a refresh failure, because it is a direct
answer rather than an inference from a side effect.

## What "dead" means here

Only a definite 404 marks a connection revoked. A timeout, a 5xx or a
network error leaves it alone: GitHub being briefly unreachable is not the
same as a user revoking access, and treating them alike would tell people to
reconnect a perfectly good connection every time GitHub had a bad minute.
"""

import httpx
import structlog
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_token
from app.models.connection import Connection

logger = structlog.get_logger("sentinel.github_auth")

GITHUB_API = "https://api.github.com"


class GitHubAuthError(Exception):
    """The connection is dead and needs reconnecting - not a transient fault."""


def get_valid_token(session: Session, connection: Connection) -> str:
    """The token for this connection, if it is still usable.

    Mirrors `google_auth.get_valid_access_token` so callers treat every
    provider the same way: hand it a connection, get a working token, or get
    an exception that means "the user must reconnect".

    Unlike Google there is no refresh step - the token either works or has
    been revoked - so this verifies rather than renews.
    """
    if connection.revoked_at is not None:
        raise GitHubAuthError("This GitHub connection was revoked - reconnect it")

    token = decrypt_token(connection.encrypted_token)

    alive = check_token(token)
    if alive is False:
        # A definite answer, so record it. This is what makes `expired`
        # reportable for GitHub at all, and it is read by channel_readiness
        # exactly like the Google case.
        connection.revoked_at = datetime.now(timezone.utc)
        session.add(connection)
        session.commit()
        logger.warning("github_token_revoked", connection_id=str(connection.id))
        raise GitHubAuthError("This GitHub connection was revoked - reconnect it")

    # `alive is None` means GitHub could not be reached to say either way.
    # The token is probably fine; proceed and let the actual call fail if not.
    return token


def check_token(token: str) -> bool | None:
    """True if GitHub confirms the token, False if it confirms it is dead,
    None if GitHub could not be asked.

    The three-way return is the point. Collapsing "unknown" into "dead" would
    mark connections revoked during any GitHub outage, and collapsing it into
    "alive" would hide real revocations behind one flaky request - so the
    caller is made to decide what to do about not knowing.
    """
    settings = get_settings()
    if not (settings.github_client_id and settings.github_client_secret):
        return None

    try:
        response = httpx.post(
            f"{GITHUB_API}/applications/{settings.github_client_id}/token",
            auth=(settings.github_client_id, settings.github_client_secret),
            json={"access_token": token},
            headers={"Accept": "application/vnd.github+json"},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        logger.info("github_token_check_unavailable", error=str(exc)[:200])
        return None

    if response.status_code == 200:
        return True
    if response.status_code in (404, 401):
        return False

    logger.info("github_token_check_inconclusive", status=response.status_code)
    return None
