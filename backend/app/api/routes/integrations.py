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
import secrets
import time
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.core.auth import InvalidTokenError, create_connect_ticket, decode_connect_ticket
from app.core.config import get_settings
from app.core.oauth import GITHUB_CONFIGURED, GOOGLE_CONFIGURED, MICROSOFT_CONFIGURED, SLACK_CONFIGURED, oauth
from app.core.security import encrypt_token
from app.models.connection import Connection, Provider
from app.models.email_summary import EmailSummary
from app.models.signal import Signal
from app.models.user import User
from app.providers.workspace_grants import GOOGLE_GRANT, MICROSOFT_GRANT
from app.services.grants import provision_grant
from app.schemas.integration import (
    ConnectTicketOut,
    GitHubRepoOut,
    GitHubPrioritySet,
    GitHubRepositoryOut,
    GitHubRepoSelect,
    ResourcePrioritySet,
    SlackChannelAdd,
    SlackChannelOut,
    SlackChannelResourceOut,
    MicrosoftCapabilitiesOut,
    MicrosoftServiceOut,
    TeamsChannelAdd,
    TeamsChannelOut,
    TeamsChannelResourceOut,
)
from app.services.github_connections import (
    account_connections,
    add_repository,
    connect_github_account,
    monitored_repositories,
    remove_repository,
    set_paused,
    set_priority,
)
from app.integrations import slack_auth
from app.integrations.graph_client import fetch_account_identity
from app.services.slack_connections import add_channel, connect_slack_workspace, monitored_channels, slack_workspace

logger = structlog.get_logger("sentinel.integrations")

# Re-exported for the existing call sites. Which providers ingest is a fact
# about each provider, declared once in app/providers - Drive is absent
# because it is searched live, and the registry is what keeps that answer the
# same here and in channel_readiness, which have to agree.
from app.providers.registry import INGESTABLE_PROVIDERS  # noqa: E402

router = APIRouter(prefix="/integrations", tags=["integrations"])

GOOGLE_CONNECT_PURPOSE = "google_connect"
GITHUB_CONNECT_PURPOSE = "github_connect"
SLACK_CONNECT_PURPOSE = "slack_connect"
MICROSOFT_CONNECT_PURPOSE = "microsoft_connect"


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


def _safe_return_path(raw: str | None) -> str:
    """Only ever return to a path inside this app.

    This value ends up in a redirect after OAuth, so accepting it verbatim
    would be an open redirect - an attacker could send a crafted connect
    link that bounces the user to an external site wearing Sentinel's
    trust. Anything that isn't a single-slash-prefixed relative path is
    discarded in favour of the dashboard.
    """
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw


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
    # Where to land after the OAuth round trip. An admin who started this
    # from inside a channel's Extensions tab should come back to that
    # channel with their configuration intact, not be dumped on the
    # dashboard to navigate back and start over.
    request.session["google_connect_return_to"] = _safe_return_path(request.query_params.get("return_to"))

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
    # Was stashed on the way out and then thrown away here. It is now the
    # owner of the resulting connection - the token belongs to whoever
    # authorized it, not to the workspace at large.
    user_id_str = request.session.pop("google_connect_user_id", None)
    return_to = _safe_return_path(request.session.pop("google_connect_return_to", None))
    # Both are required now: without the user id there is no owner to
    # attach the token to, and guessing one would hand someone else's
    # mailbox to whoever happened to finish the flow.
    if not workspace_id_str or not user_id_str:
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
    upsert_google_connections(
        session, workspace_id=workspace_id, user_id=uuid.UUID(user_id_str), google_email=google_email, encrypted_token=encrypted
    )
    _queue_first_sync(session, workspace_id, uuid.UUID(user_id_str))

    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{get_settings().frontend_base_url}{return_to}{separator}connected=google")


# --- Microsoft 365 ----------------------------------------------------------
#
# The exact three-step shape as Google - ticket, redirect, callback - because
# the constraint is identical (a full-page redirect cannot carry an auth
# header). The only differences are the authlib client (microsoft_data) and the
# provisioner call: one grant fans out into the Microsoft child services via the
# SAME generic provision_grant Google now uses. Sprint 1 provisions Outlook Mail
# and Calendar; later sprints extend MICROSOFT_GRANT's service list, no route
# change.
@router.post("/microsoft/connect-ticket", response_model=ConnectTicketOut)
def create_microsoft_connect_ticket(
    user: User = Depends(get_current_user),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> ConnectTicketOut:
    if not MICROSOFT_CONFIGURED:
        raise HTTPException(status_code=501, detail="Microsoft 365 integration is not configured yet")
    ticket = create_connect_ticket(user_id=user.id, workspace_id=workspace_id, purpose=MICROSOFT_CONNECT_PURPOSE)
    return ConnectTicketOut(ticket=ticket)


@router.get("/microsoft/connect")
async def microsoft_connect(request: Request, ticket: str):
    if not MICROSOFT_CONFIGURED:
        raise HTTPException(status_code=501, detail="Microsoft 365 integration is not configured yet")
    try:
        user_id, workspace_id = decode_connect_ticket(ticket, expected_purpose=MICROSOFT_CONNECT_PURPOSE)
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="This connect link is invalid or has expired - try again")

    request.session["microsoft_connect_user_id"] = str(user_id)
    request.session["microsoft_connect_workspace_id"] = str(workspace_id)
    request.session["microsoft_connect_return_to"] = _safe_return_path(request.query_params.get("return_to"))

    redirect_uri = f"{get_settings().backend_base_url}/integrations/microsoft/callback"
    # prompt=consent forces a real consent screen (so a scope bump takes effect
    # on reconnect); offline_access in the scope is what yields a refresh_token.
    return await oauth.microsoft_data.authorize_redirect(request, redirect_uri, prompt="consent")


@router.get("/microsoft/callback")
async def microsoft_connect_callback(request: Request, session: Session = Depends(get_db)):
    if not MICROSOFT_CONFIGURED:
        raise HTTPException(status_code=501, detail="Microsoft 365 integration is not configured yet")

    workspace_id_str = request.session.pop("microsoft_connect_workspace_id", None)
    user_id_str = request.session.pop("microsoft_connect_user_id", None)
    return_to = _safe_return_path(request.session.pop("microsoft_connect_return_to", None))
    if not workspace_id_str or not user_id_str:
        return RedirectResponse(f"{get_settings().frontend_base_url}/?microsoft_error=session_expired")

    # No ID token is requested for this client (see core/oauth.py), so this is
    # a plain OAuth2 token exchange with nothing for authlib to validate -
    # deliberately avoids the "common" endpoint's unsubstituted issuer
    # template, which crashes strict ID-token validation. Account identity
    # comes straight from Graph instead, right below.
    token = await oauth.microsoft_data.authorize_access_token(request)
    access_token = token["access_token"]
    refresh_token = token.get("refresh_token")
    microsoft_account = fetch_account_identity(access_token)

    if not refresh_token:
        return RedirectResponse(f"{get_settings().frontend_base_url}/?microsoft_error=no_refresh_token")

    expires_at_ts = token.get("expires_at") or (time.time() + token.get("expires_in", 3600))
    expires_at = datetime.fromtimestamp(expires_at_ts, tz=timezone.utc)
    encrypted = encrypt_token(
        json.dumps({"access_token": access_token, "refresh_token": refresh_token, "expires_at": expires_at.isoformat()})
    )

    workspace_id = uuid.UUID(workspace_id_str)
    provision_grant(
        session, workspace_id=workspace_id, user_id=uuid.UUID(user_id_str), grant=MICROSOFT_GRANT,
        account_identity=microsoft_account, encrypted_token=encrypted,
    )
    _queue_first_sync(session, workspace_id, uuid.UUID(user_id_str))

    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{get_settings().frontend_base_url}{return_to}{separator}connected=microsoft")


def _queue_first_sync(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Sync immediately after connecting, instead of waiting for the poll.

    Without this, a new user connects Google and then stares at an empty
    Mail page, empty Calendar and empty Attention feed until the scheduled
    poll fires - up to `ingestion_poll_interval_seconds` later (6 hours by
    default). At the single moment of highest intent, the product looks
    broken. Confirmed real on a fresh account: connections existed with
    last_synced_at=None and zero signals.

    Queued rather than run inline so the user isn't held on a spinner
    mid-OAuth-redirect, and guarded so a broker outage degrades to "data
    appears at the next poll" rather than breaking the connect flow itself.
    """
    from app.workers.tasks import ingest_connection as ingest_task

    connections = session.execute(
        select(Connection).where(Connection.workspace_id == workspace_id, Connection.user_id == user_id)
    ).scalars().all()
    for connection in connections:
        # Drive deliberately has no ingestion handler - files are searched
        # live and never cached (see google_drive_client.py). Queuing it
        # would just raise and burn three retries.
        if connection.provider not in INGESTABLE_PROVIDERS:
            continue
        try:
            ingest_task.delay(str(connection.id))
        except Exception:
            logger.warning("first_sync_enqueue_failed", connection_id=str(connection.id), provider=connection.provider.value)


def upsert_google_connections(
    session: Session, *, workspace_id: uuid.UUID, user_id: uuid.UUID, google_email: str, encrypted_token: str
) -> None:
    """One Google account per person per workspace - now a thin call into the
    generalized grant provisioner (services/grants.py), shared with Microsoft.

    The behaviour is unchanged: keyed on (workspace, user, provider); a token
    delegates one individual's access; re-connecting a different account as the
    same person replaces their own connections and purges the now-unreadable
    signals, never a teammate's.
    """
    provision_grant(
        session,
        workspace_id=workspace_id, user_id=user_id, grant=GOOGLE_GRANT,
        account_identity=google_email, encrypted_token=encrypted_token,
    )


# --- GitHub -----------------------------------------------------------------
#
# Same three-step shape as Google - ticket, redirect, callback - because the
# constraint is the same: a full-page OAuth redirect cannot carry an
# Authorization header, so the authenticated fetch that starts it exchanges
# the session for a short-lived ticket that is safe to put in a URL.
#
# What differs is the end of the flow. A GitHub OAuth App issues a
# non-expiring access token and no refresh token, so there is nothing to
# renew and the stored value is the token itself rather than Google's
# {access,refresh,expires} blob - which is also what github_client.py has
# always expected.
#
# And a token is not yet a connection: it can read many repositories, and
# Sentinel watches one. So the callback records the account and leaves the
# repository unset, and the user picks from the repositories the token can
# genuinely see (see /github/repos). Typing a repo name by hand would be a
# guess that fails silently at the first sync.


@router.post("/github/connect-ticket", response_model=ConnectTicketOut)
def create_github_connect_ticket(
    user: User = Depends(get_current_user),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> ConnectTicketOut:
    if not GITHUB_CONFIGURED:
        raise HTTPException(status_code=501, detail="GitHub integration is not configured yet")
    ticket = create_connect_ticket(user_id=user.id, workspace_id=workspace_id, purpose=GITHUB_CONNECT_PURPOSE)
    return ConnectTicketOut(ticket=ticket)


@router.get("/github/connect")
async def github_connect(request: Request, ticket: str):
    if not GITHUB_CONFIGURED:
        raise HTTPException(status_code=501, detail="GitHub integration is not configured yet")
    try:
        user_id, workspace_id = decode_connect_ticket(ticket, expected_purpose=GITHUB_CONNECT_PURPOSE)
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="This connect link is invalid or has expired - try again")

    request.session["github_connect_user_id"] = str(user_id)
    request.session["github_connect_workspace_id"] = str(workspace_id)
    request.session["github_connect_return_to"] = _safe_return_path(request.query_params.get("return_to"))

    redirect_uri = f"{get_settings().backend_base_url}/integrations/github/callback"
    return await oauth.github.authorize_redirect(request, redirect_uri)


@router.get("/github/callback")
async def github_connect_callback(request: Request, session: Session = Depends(get_db)):
    if not GITHUB_CONFIGURED:
        raise HTTPException(status_code=501, detail="GitHub integration is not configured yet")

    workspace_id_str = request.session.pop("github_connect_workspace_id", None)
    user_id_str = request.session.pop("github_connect_user_id", None)
    return_to = _safe_return_path(request.session.pop("github_connect_return_to", None))
    if not workspace_id_str or not user_id_str:
        return RedirectResponse(f"{get_settings().frontend_base_url}/?github_error=session_expired")

    token = await oauth.github.authorize_access_token(request)
    access_token = token.get("access_token")
    if not access_token:
        # GitHub reports a refused or expired authorization code in the body
        # rather than with an error status, so this is a normal outcome to
        # handle, not an exceptional one.
        return RedirectResponse(f"{get_settings().frontend_base_url}/?github_error=no_token")

    from app.integrations.github_client import GitHubClient

    try:
        with GitHubClient(access_token) as client:
            account = client.get_authenticated_user()
    except Exception:
        logger.warning("github_identity_lookup_failed")
        return RedirectResponse(f"{get_settings().frontend_base_url}/?github_error=identity_failed")

    login = account.get("login") or "unknown-github-account"
    connect_github_account(
        session,
        workspace_id=uuid.UUID(workspace_id_str),
        user_id=uuid.UUID(user_id_str),
        login=login,
        encrypted_token=encrypt_token(access_token),
    )

    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{get_settings().frontend_base_url}{return_to}{separator}connected=github")


# A `login` alias kept so tests and older imports of the previous helper name
# continue to resolve; the real logic lives in services/github_connections.py.
def upsert_github_connection(session, *, workspace_id, user_id, login, encrypted_token):  # noqa: ANN001
    """Deprecated shim for connect_github_account (single-repo era name)."""
    connect_github_account(
        session, workspace_id=workspace_id, user_id=user_id, login=login, encrypted_token=encrypted_token
    )
    return _account_anchor(session, workspace_id, user_id)


def _account_anchor(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Connection:
    connections = account_connections(session, workspace_id, user_id)
    return next((c for c in connections if not c.repo), connections[0] if connections else None)


# --- Slack (Phase 0: connect the workspace) --------------------------------
# The same connect-ticket + session + callback shape as GitHub, so the flow a
# user sees is identical across providers. Slack's OAuth v2 is driven manually
# (see integrations/slack_auth.py) rather than through authlib.


@router.post("/slack/connect-ticket", response_model=ConnectTicketOut)
def create_slack_connect_ticket(
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> ConnectTicketOut:
    """Mint a short-lived signed ticket carrying who is connecting. The OAuth
    callback has no auth header, so identity rides in this ticket (validated)
    plus the session - exactly as the Google/GitHub flows do."""
    ticket = create_connect_ticket(user_id=user.id, workspace_id=workspace_id, purpose=SLACK_CONNECT_PURPOSE)
    return ConnectTicketOut(ticket=ticket)


@router.get("/slack/connect")
def slack_connect(request: Request, ticket: str):
    if not SLACK_CONFIGURED:
        raise HTTPException(status_code=501, detail="Slack integration is not configured yet")
    try:
        user_id, workspace_id = decode_connect_ticket(ticket, expected_purpose=SLACK_CONNECT_PURPOSE)
    except InvalidTokenError:
        raise HTTPException(status_code=400, detail="This connect link is invalid or has expired - try again")

    state = secrets.token_urlsafe(24)
    request.session["slack_connect_user_id"] = str(user_id)
    request.session["slack_connect_workspace_id"] = str(workspace_id)
    request.session["slack_connect_return_to"] = _safe_return_path(request.query_params.get("return_to"))
    request.session["slack_oauth_state"] = state

    redirect_uri = f"{get_settings().backend_base_url}/integrations/slack/callback"
    return RedirectResponse(slack_auth.authorize_url(
        client_id=get_settings().slack_client_id, redirect_uri=redirect_uri, state=state,
    ))


@router.get("/slack/callback")
def slack_connect_callback(request: Request, session: Session = Depends(get_db)):
    if not SLACK_CONFIGURED:
        raise HTTPException(status_code=501, detail="Slack integration is not configured yet")

    frontend = get_settings().frontend_base_url
    workspace_id_str = request.session.pop("slack_connect_workspace_id", None)
    user_id_str = request.session.pop("slack_connect_user_id", None)
    expected_state = request.session.pop("slack_oauth_state", None)
    return_to = _safe_return_path(request.session.pop("slack_connect_return_to", None))
    if not workspace_id_str or not user_id_str:
        return RedirectResponse(f"{frontend}/?slack_error=session_expired")

    # State check: the value we handed Slack must be the one that came back,
    # or this is a forged/replayed callback, not our redirect.
    if not expected_state or request.query_params.get("state") != expected_state:
        return RedirectResponse(f"{frontend}/?slack_error=state_mismatch")

    error = request.query_params.get("error")
    code = request.query_params.get("code")
    if error or not code:
        return RedirectResponse(f"{frontend}/?slack_error={error or 'no_code'}")

    redirect_uri = f"{get_settings().backend_base_url}/integrations/slack/callback"
    try:
        token_data = slack_auth.exchange_code(
            client_id=get_settings().slack_client_id,
            client_secret=get_settings().slack_client_secret,
            code=code,
            redirect_uri=redirect_uri,
        )
        bot_token = token_data.get("access_token")
        if not bot_token:
            return RedirectResponse(f"{frontend}/?slack_error=no_token")
        # Verify the token and learn the workspace it belongs to. auth.test is
        # authoritative for team identity, more so than the OAuth response.
        identity = slack_auth.auth_test(bot_token)
    except slack_auth.SlackAuthError as exc:
        logger.warning("slack_oauth_failed", error=str(exc)[:200])
        return RedirectResponse(f"{frontend}/?slack_error={str(exc)[:80]}")
    except Exception:
        logger.warning("slack_oauth_unexpected")
        return RedirectResponse(f"{frontend}/?slack_error=connect_failed")

    team = token_data.get("team") or {}
    team_id = team.get("id") or identity.get("team_id") or "unknown-team"
    team_name = team.get("name") or identity.get("team") or "Slack workspace"

    connect_slack_workspace(
        session,
        workspace_id=uuid.UUID(workspace_id_str),
        user_id=uuid.UUID(user_id_str),
        team_id=team_id,
        team_name=team_name,
        encrypted_token=encrypt_token(bot_token),
    )

    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{frontend}{return_to}{separator}connected=slack")


@router.get("/slack/channels", response_model=list[SlackChannelOut])
def list_slack_channels(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[SlackChannelOut]:
    """The public channels this workspace has, each flagged with whether the
    bot is a member (the prerequisite for monitoring it). Phase 1 discovery -
    the picker channel management will be built on. Scoped to the caller's own
    Slack grant; one member's workspace is never listed for another."""
    from app.core.security import decrypt_token
    from app.integrations.slack_client import SlackClient, SlackClientError

    conn = slack_workspace(session, workspace_id, user.id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connect Slack first")

    try:
        with SlackClient(decrypt_token(conn.encrypted_token)) as client:
            channels = client.list_channels()
    except SlackClientError as exc:
        # A revoked/invalid token surfaces here as Slack's own error string.
        raise HTTPException(status_code=409, detail=f"Slack: {exc}") from exc
    except Exception as exc:
        logger.warning("slack_channel_list_failed", error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="Slack could not be reached just now") from exc

    monitored_ids = {c.repo for c in monitored_channels(session, workspace_id, user.id)}
    return [SlackChannelOut(**ch, monitored=ch["id"] in monitored_ids) for ch in channels]


# --- Slack channel management (Phase 1) ------------------------------------
# A monitored channel is a Connection, managed exactly like a GitHub repository
# - list / add / remove / pause / resume / classify - over the same shared
# provider_account helper. No Slack-specific resource logic.


def _owned_slack_channel(
    session: Session, connection_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> Connection:
    """A monitored Slack channel that belongs to this caller, or 404. Ownership
    is checked against the record, not the path - another member's channel, or
    another provider's connection, is never found here."""
    connection = session.get(Connection, connection_id)
    if (
        connection is None
        or connection.provider != Provider.SLACK
        or connection.workspace_id != workspace_id
        or connection.user_id != user_id
        or not connection.repo
    ):
        raise HTTPException(status_code=404, detail="Not found")
    return connection


def _slack_channel_out(session: Session, connection: Connection) -> SlackChannelResourceOut:
    from app.services.connection_state import connection_state

    return SlackChannelResourceOut(
        connection_id=connection.id,
        channel_id=connection.repo,
        name=connection.full_name,
        state=connection_state(connection).value,
        paused=connection.paused_at is not None,
        priority=connection.priority.value,
        last_synced_at=connection.last_synced_at,
        last_success_at=connection.last_success_at,
        signal_count=session.query(Signal).filter(Signal.connection_id == connection.id).count(),
        last_sync=connection.last_sync_meta,
    )


@router.get("/slack/monitored", response_model=list[SlackChannelResourceOut])
def list_monitored_channels(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[SlackChannelResourceOut]:
    """The channels this person is monitoring, each with its own health."""
    return [_slack_channel_out(session, c) for c in monitored_channels(session, workspace_id, user.id)]


@router.post("/slack/monitored", response_model=SlackChannelResourceOut, status_code=201)
def add_monitored_channel(
    payload: SlackChannelAdd,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> SlackChannelResourceOut:
    """Start monitoring a channel. The bot must already be a member - that is
    the access boundary, so it is verified against the live channel rather than
    trusted from the request, and the channel's current name is taken from
    Slack rather than the client."""
    from app.core.security import decrypt_token
    from app.integrations.slack_client import SlackClient, SlackClientError

    conn = slack_workspace(session, workspace_id, user.id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connect Slack first")

    try:
        with SlackClient(decrypt_token(conn.encrypted_token)) as client:
            channels = client.list_channels()
    except SlackClientError as exc:
        raise HTTPException(status_code=409, detail=f"Slack: {exc}") from exc
    except Exception as exc:
        logger.warning("slack_add_channel_lookup_failed", error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="Slack could not be reached just now") from exc

    match = next((ch for ch in channels if ch["id"] == payload.channel_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="That channel isn't in this workspace")
    if not match["is_member"]:
        raise HTTPException(status_code=409, detail="Invite the bot to this channel first (/invite @sentinel)")

    channel = add_channel(
        session, workspace_id=workspace_id, user_id=user.id,
        channel_id=payload.channel_id, channel_name=match["name"],
    )
    return _slack_channel_out(session, channel)


@router.delete("/slack/monitored/{connection_id}", status_code=204)
def remove_monitored_channel(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> None:
    from app.services.provider_account import remove_resource

    remove_resource(session, _owned_slack_channel(session, connection_id, workspace_id, user.id))


@router.post("/slack/monitored/{connection_id}/pause", response_model=SlackChannelResourceOut)
def pause_monitored_channel(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> SlackChannelResourceOut:
    from app.services.provider_account import set_paused

    connection = set_paused(session, _owned_slack_channel(session, connection_id, workspace_id, user.id), paused=True)
    return _slack_channel_out(session, connection)


@router.post("/slack/monitored/{connection_id}/resume", response_model=SlackChannelResourceOut)
def resume_monitored_channel(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> SlackChannelResourceOut:
    from app.services.provider_account import set_paused

    connection = set_paused(session, _owned_slack_channel(session, connection_id, workspace_id, user.id), paused=False)
    return _slack_channel_out(session, connection)


@router.post("/slack/monitored/{connection_id}/sync", response_model=SlackChannelResourceOut)
def sync_monitored_channel(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> SlackChannelResourceOut:
    """Sync one channel now, rather than at the next scheduled poll."""
    connection = _owned_slack_channel(session, connection_id, workspace_id, user.id)
    if connection.paused_at is not None:
        raise HTTPException(status_code=409, detail="This channel is paused - resume it first")
    _sync_one(session, connection)
    return _slack_channel_out(session, connection)


@router.patch("/slack/monitored/{connection_id}/priority", response_model=SlackChannelResourceOut)
def classify_monitored_channel(
    connection_id: uuid.UUID,
    payload: ResourcePrioritySet,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> SlackChannelResourceOut:
    """Classify how much a channel matters - the same five levels a repository
    uses. Marking a channel CRITICAL is what will let its silence become a
    proactive situation once ingestion lands."""
    from app.models.connection import ResourcePriority
    from app.services.provider_account import set_priority

    connection = _owned_slack_channel(session, connection_id, workspace_id, user.id)
    set_priority(session, connection, ResourcePriority(payload.priority))
    return _slack_channel_out(session, connection)


@router.get("/github/repos", response_model=list[GitHubRepoOut])
def list_github_repos(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[GitHubRepoOut]:
    """The repositories this person's token can read, each flagged with whether
    it is already monitored.

    Scoped to the caller's own account - one member's GitHub access is never
    listed for another. The `monitored` flag is what lets the picker show a
    repository as already-watched rather than offering it a second time.
    """
    from app.integrations.github_auth import GitHubAuthError, get_valid_token
    from app.integrations.github_client import GitHubClient

    account = account_connections(session, workspace_id, user.id)
    if not account:
        raise HTTPException(status_code=404, detail="Connect GitHub first")

    watched = {
        f"{c.org.lower()}/{c.repo.lower()}": c.id
        for c in account if c.repo
    }
    try:
        token = get_valid_token(session, account[0])
        with GitHubClient(token) as client:
            repos = client.list_repositories()
    except GitHubAuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("github_repo_list_failed", error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="GitHub could not be reached just now") from exc

    out = []
    for r in repos:
        conn_id = watched.get(r["full_name"].lower())
        out.append(GitHubRepoOut(**r, monitored=conn_id is not None, connection_id=conn_id))
    return out


@router.get("/github/repositories", response_model=list[GitHubRepositoryOut])
def list_monitored_repositories(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[GitHubRepositoryOut]:
    """What Sentinel is actually watching, with each repository's own health.

    This is the management view - one row per monitored repository, carrying
    its own sync timestamps and paused/revoked state, because the whole point
    of multi-repo is that these are independent.
    """
    return [_repository_out(session, c) for c in monitored_repositories(session, workspace_id, user.id)]


@router.post("/github/repositories", response_model=GitHubRepositoryOut, status_code=201)
def add_monitored_repository(
    payload: GitHubRepoSelect,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> GitHubRepositoryOut:
    """Start monitoring one more repository, verified before it is stored.

    A repository the token cannot read is refused here rather than accepted
    and left to fail silently on every later sync - the same guarantee the
    single-repo flow made, now per repository.
    """
    from app.integrations.github_auth import GitHubAuthError, get_valid_token
    from app.integrations.github_client import GitHubClient

    account = account_connections(session, workspace_id, user.id)
    if not account:
        raise HTTPException(status_code=404, detail="Connect GitHub first")

    try:
        token = get_valid_token(session, account[0])
        with GitHubClient(token) as client:
            allowed = {r["full_name"].lower() for r in client.list_repositories()}
    except GitHubAuthError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("github_repo_verify_failed", error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="GitHub could not be reached just now") from exc

    if f"{payload.org}/{payload.repo}".lower() not in allowed:
        raise HTTPException(status_code=403, detail="Your GitHub account cannot read that repository")

    connection = add_repository(session, workspace_id=workspace_id, user_id=user.id, org=payload.org, repo=payload.repo)
    _sync_one(session, connection)
    return _repository_out(session, connection)


@router.delete("/github/repositories/{connection_id}", status_code=204)
def remove_monitored_repository(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> None:
    remove_repository(session, _owned_repo(session, connection_id, workspace_id, user.id))


@router.post("/github/repositories/{connection_id}/pause", response_model=GitHubRepositoryOut)
def pause_monitored_repository(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> GitHubRepositoryOut:
    connection = set_paused(session, _owned_repo(session, connection_id, workspace_id, user.id), paused=True)
    return _repository_out(session, connection)


@router.post("/github/repositories/{connection_id}/resume", response_model=GitHubRepositoryOut)
def resume_monitored_repository(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> GitHubRepositoryOut:
    connection = set_paused(session, _owned_repo(session, connection_id, workspace_id, user.id), paused=False)
    # Resuming should pick up whatever was missed while paused, without waiting
    # for the next scheduled poll.
    _sync_one(session, connection)
    return _repository_out(session, connection)


@router.patch("/github/repositories/{connection_id}/priority", response_model=GitHubRepositoryOut)
def classify_monitored_repository(
    connection_id: uuid.UUID,
    payload: GitHubPrioritySet,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> GitHubRepositoryOut:
    """Classify how much a repository matters.

    Not cosmetic: marking a repository CRITICAL is what lets its silence
    become a proactive situation, and lowering it turns that off. The context
    a person supplies here is exactly what keeps activity-based attention from
    firing on every quiet side project.
    """
    from app.models.connection import ResourcePriority

    connection = _owned_repo(session, connection_id, workspace_id, user.id)
    set_priority(session, connection, ResourcePriority(payload.priority))
    return _repository_out(session, connection)


@router.post("/github/repositories/{connection_id}/sync", response_model=GitHubRepositoryOut)
def sync_monitored_repository(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> GitHubRepositoryOut:
    """Sync one repository now, rather than at the next scheduled poll."""
    connection = _owned_repo(session, connection_id, workspace_id, user.id)
    if connection.paused_at is not None:
        raise HTTPException(status_code=409, detail="This repository is paused - resume it first")
    _sync_one(session, connection)
    return _repository_out(session, connection)


def _owned_repo(session: Session, connection_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Connection:
    """A GitHub connection that belongs to this caller, or 404.

    Ownership is checked against the record, not the path: another member's
    repository, or another provider's connection, is not found here even by a
    workspace admin - the same rule every scoped mutation in the codebase
    follows.
    """
    connection = session.get(Connection, connection_id)
    if (
        connection is None
        or connection.provider != Provider.GITHUB
        or connection.workspace_id != workspace_id
        or connection.user_id != user_id
        or not connection.repo
    ):
        raise HTTPException(status_code=404, detail="Not found")
    return connection


def _sync_one(session: Session, connection: Connection) -> None:
    """Queue one repository's ingestion. Degrades to "at the next poll" if the
    broker is down rather than failing the request the user just made."""
    from app.workers.tasks import ingest_connection as ingest_task

    try:
        ingest_task.delay(str(connection.id))
    except Exception:
        logger.warning("github_sync_enqueue_failed", connection_id=str(connection.id))


def _repository_out(session: Session, connection: Connection) -> "GitHubRepositoryOut":
    from app.services.connection_state import connection_state

    return GitHubRepositoryOut(
        connection_id=connection.id,
        org=connection.org,
        repo=connection.repo,
        full_name=connection.full_name,
        state=connection_state(connection).value,
        priority=connection.priority.value,
        paused=connection.paused_at is not None,
        last_synced_at=connection.last_synced_at,
        last_success_at=connection.last_success_at,
        signal_count=session.query(Signal).filter(Signal.connection_id == connection.id).count(),
    )


# --- Microsoft Teams (Sprint 2, Phase 1: metadata + channel management) -----
#
# Teams rides the Microsoft grant - no second OAuth. Discovery lists the teams
# and channels the connected account belongs to; management is the same
# list/add/remove/pause/resume/classify surface Slack and GitHub already use,
# over the same shared provider_account helper. Nothing here is Teams-specific
# except the Graph calls themselves.


def _teams_token(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """The Microsoft grant's access token, reached via the Teams anchor row."""
    from app.integrations.microsoft_auth import get_valid_access_token as ms_token
    from app.services.teams_connections import teams_account

    conn = teams_account(session, workspace_id, user_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connect Microsoft 365 first")
    return ms_token(session, conn)


@router.get("/microsoft/teams/channels", response_model=list[TeamsChannelOut])
def list_teams_channels(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[TeamsChannelOut]:
    """Every channel of every team the connected account belongs to, flagged with
    whether Sentinel already monitors it. Scoped to the caller's own grant."""
    from app.integrations.graph_client import GraphClient
    from app.services.teams_connections import monitored_channels as monitored_teams_channels

    token = _teams_token(session, workspace_id, user.id)
    monitored_ids = {c.repo for c in monitored_teams_channels(session, workspace_id, user.id)}
    out: list[TeamsChannelOut] = []
    try:
        with GraphClient(token) as client:
            for team in client.list_joined_teams():
                for ch in client.list_channels(team["id"]):
                    out.append(TeamsChannelOut(
                        id=ch["id"], name=ch["name"], team_id=team["id"], team_name=team["name"],
                        description=ch["description"], membership_type=ch["membership_type"],
                        monitored=ch["id"] in monitored_ids,
                    ))
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("teams_channel_list_failed", error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="Microsoft Teams could not be reached just now") from exc
    return out


def _owned_teams_channel(
    session: Session, connection_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> Connection:
    """A monitored Teams channel belonging to this caller, or 404. Ownership is
    checked against the record, never the path."""
    connection = session.get(Connection, connection_id)
    if (
        connection is None
        or connection.provider != Provider.MICROSOFT_TEAMS
        or connection.workspace_id != workspace_id
        or connection.user_id != user_id
        or not connection.repo
    ):
        raise HTTPException(status_code=404, detail="Not found")
    return connection


def _teams_channel_out(session: Session, connection: Connection) -> TeamsChannelResourceOut:
    from app.services.connection_state import connection_state

    meta = connection.last_sync_meta or {}
    return TeamsChannelResourceOut(
        connection_id=connection.id,
        channel_id=connection.repo,
        team_id=connection.org or "",
        name=connection.full_name,
        state=connection_state(connection).value,
        paused=connection.paused_at is not None,
        priority=connection.priority.value,
        last_synced_at=connection.last_synced_at,
        signal_count=session.query(Signal).filter(Signal.connection_id == connection.id).count(),
        # Honest capability reporting: None until first sync, then whether this
        # tenant actually grants message access (see the ingestion handler).
        messages_accessible=meta.get("messages_accessible"),
    )


@router.get("/microsoft/teams/monitored", response_model=list[TeamsChannelResourceOut])
def list_monitored_teams_channels(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[TeamsChannelResourceOut]:
    from app.services.teams_connections import monitored_channels as monitored_teams_channels

    return [_teams_channel_out(session, c) for c in monitored_teams_channels(session, workspace_id, user.id)]


@router.post("/microsoft/teams/monitored", response_model=TeamsChannelResourceOut, status_code=201)
def add_monitored_teams_channel(
    payload: TeamsChannelAdd,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> TeamsChannelResourceOut:
    """Start monitoring one Teams channel."""
    from app.services.teams_connections import TeamsAccountError
    from app.services.teams_connections import add_channel as add_teams_channel

    try:
        channel = add_teams_channel(
            session, workspace_id=workspace_id, user_id=user.id,
            team_id=payload.team_id, team_name=payload.team_name,
            channel_id=payload.channel_id, channel_name=payload.channel_name,
        )
    except TeamsAccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _queue_first_sync(session, workspace_id, user.id)
    return _teams_channel_out(session, channel)


@router.delete("/microsoft/teams/monitored/{connection_id}", status_code=204)
def remove_monitored_teams_channel(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> None:
    from app.services.provider_account import remove_resource

    remove_resource(session, _owned_teams_channel(session, connection_id, workspace_id, user.id))


@router.post("/microsoft/teams/monitored/{connection_id}/pause", response_model=TeamsChannelResourceOut)
def pause_monitored_teams_channel(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> TeamsChannelResourceOut:
    from app.services.provider_account import set_paused as pause_resource

    connection = _owned_teams_channel(session, connection_id, workspace_id, user.id)
    return _teams_channel_out(session, pause_resource(session, connection, paused=True))


@router.post("/microsoft/teams/monitored/{connection_id}/resume", response_model=TeamsChannelResourceOut)
def resume_monitored_teams_channel(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> TeamsChannelResourceOut:
    from app.services.provider_account import set_paused as pause_resource

    connection = _owned_teams_channel(session, connection_id, workspace_id, user.id)
    return _teams_channel_out(session, pause_resource(session, connection, paused=False))


@router.patch("/microsoft/teams/monitored/{connection_id}/priority", response_model=TeamsChannelResourceOut)
def classify_monitored_teams_channel(
    connection_id: uuid.UUID,
    payload: ResourcePrioritySet,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> TeamsChannelResourceOut:
    """Classify how much a channel matters - the same five levels a repository or
    a Slack channel uses. CRITICAL is what promotes a mention in it to a finding,
    and what makes its silence meaningful."""
    from app.models.connection import ResourcePriority
    from app.services.provider_account import set_priority as prioritize

    connection = _owned_teams_channel(session, connection_id, workspace_id, user.id)
    return _teams_channel_out(session, prioritize(session, connection, ResourcePriority(payload.priority)))


@router.post("/microsoft/teams/monitored/{connection_id}/sync", response_model=TeamsChannelResourceOut)
def sync_monitored_teams_channel(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> TeamsChannelResourceOut:
    """Sync one channel now, rather than at the next scheduled poll."""
    connection = _owned_teams_channel(session, connection_id, workspace_id, user.id)
    if connection.paused_at is not None:
        raise HTTPException(status_code=409, detail="This channel is paused - resume it first")
    _sync_one(session, connection)
    return _teams_channel_out(session, connection)


@router.get("/microsoft/capabilities", response_model=MicrosoftCapabilitiesOut)
def microsoft_capabilities(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> MicrosoftCapabilitiesOut:
    """What the connected Microsoft account can actually do.

    Every supported service is listed, whether or not this account has it -
    an unavailable service is a capability statement ("requires a work or
    school account"), never an error. The account type is detected by asking
    Microsoft, so connecting a different account changes this automatically.
    """
    from app.services.microsoft_capabilities import AccountType, MicrosoftAccount, capabilities_for, detect_account

    conns = session.execute(
        select(Connection).where(
            Connection.workspace_id == workspace_id,
            Connection.user_id == user.id,
            Connection.provider.in_(MICROSOFT_GRANT.providers + MICROSOFT_GRANT.anchors),
        )
    ).scalars().all()

    if not conns:
        return MicrosoftCapabilitiesOut(
            connected=False, account_type="none", account_type_label="Not connected",
            account=None, tenant_name=None, services=[],
        )

    # Detection needs a live token; a failure degrades to UNKNOWN rather than
    # failing the page, so the UI can still list the services.
    anchor = conns[0]
    try:
        from app.integrations.microsoft_auth import get_valid_access_token as ms_token

        token = ms_token(session, anchor)
        account = detect_account(token, cache_key=(str(anchor.id), anchor.org))
    except Exception as exc:  # noqa: BLE001 - never break the connection page
        logger.warning("microsoft_capabilities_token_failed", error=str(exc)[:160])
        account = MicrosoftAccount(AccountType.UNKNOWN, "Microsoft account", detected=False)

    # Which services Sentinel actually holds a connection for, so the UI can
    # tell "available and connected" from "available, not set up yet".
    connected_keys = set()
    for c in conns:
        if c.provider == Provider.MICROSOFT_OUTLOOK_MAIL:
            connected_keys.add("outlook_mail")
        elif c.provider == Provider.MICROSOFT_OUTLOOK_CALENDAR:
            connected_keys.add("outlook_calendar")
        elif c.provider == Provider.MICROSOFT_TEAMS and c.repo:
            connected_keys.add("teams")
        elif c.provider == Provider.MICROSOFT_ONEDRIVE:
            connected_keys.add("onedrive")
        elif c.provider == Provider.MICROSOFT_ONENOTE:
            connected_keys.add("onenote")
        elif c.provider == Provider.MICROSOFT_TODO:
            connected_keys.add("todo")

    services = [
        MicrosoftServiceOut(
            key=cap.key, label=cap.label, description=cap.description,
            available=cap.available, status=cap.status, reason=cap.reason,
            unlock=cap.unlock, connected=cap.key in connected_keys,
        )
        for cap in capabilities_for(account)
    ]
    return MicrosoftCapabilitiesOut(
        connected=True,
        account_type=account.account_type.value,
        account_type_label=account.type_label,
        account=anchor.org,
        tenant_name=account.tenant_name,
        services=services,
    )
