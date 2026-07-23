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

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.core.auth import InvalidTokenError, create_connect_ticket, decode_connect_ticket
from app.core.config import get_settings
from app.core.oauth import GITHUB_CONFIGURED, GOOGLE_CONFIGURED, oauth
from app.core.security import encrypt_token
from app.models.connection import Connection, Provider
from app.models.email_summary import EmailSummary
from app.models.signal import Signal
from app.models.user import User
from app.schemas.integration import (
    ConnectTicketOut,
    GitHubRepoOut,
    GitHubRepositoryOut,
    GitHubRepoSelect,
)
from app.services.github_connections import (
    account_connections,
    add_repository,
    connect_github_account,
    monitored_repositories,
    remove_repository,
    set_paused,
)

logger = structlog.get_logger("sentinel.integrations")

# Re-exported for the existing call sites. Which providers ingest is a fact
# about each provider, declared once in app/providers - Drive is absent
# because it is searched live, and the registry is what keeps that answer the
# same here and in channel_readiness, which have to agree.
from app.providers.registry import INGESTABLE_PROVIDERS  # noqa: E402

router = APIRouter(prefix="/integrations", tags=["integrations"])

GOOGLE_CONNECT_PURPOSE = "google_connect"
GITHUB_CONNECT_PURPOSE = "github_connect"


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
    """One Google account per person per workspace.

    Keyed on (workspace, user, provider). The user is part of the key
    because an OAuth token delegates one individual's access: without it,
    two members of a shared workspace collided, and the second to connect
    replaced the first's connection and deleted their synced signals -
    reproduced before this change, not theorised.

    Re-connecting a *different* Google account as the same person still
    replaces their own connection, since the previously synced signals
    describe a mailbox this account can no longer read. That purge is
    scoped to that user's own connection and never touches a teammate's.
    """
    for provider, label in [(Provider.GOOGLE_CALENDAR, "calendar"), (Provider.GMAIL, "gmail"), (Provider.GOOGLE_DRIVE, "drive")]:
        existing = session.execute(
            select(Connection).where(
                Connection.workspace_id == workspace_id,
                Connection.user_id == user_id,
                Connection.provider == provider,
            )
        ).scalars().first()
        if existing is not None:
            if existing.org != google_email:
                logger.info(
                    "google_account_replaced",
                    provider=provider.value, old=existing.org, new=google_email,
                    workspace_id=str(workspace_id), user_id=str(user_id),
                )
                session.query(Signal).filter(Signal.connection_id == existing.id).delete()
                if provider == Provider.GMAIL:
                    # Summaries are keyed by workspace+message; only this
                    # user's messages are going away, and a stale summary
                    # for a message nobody can fetch is dead weight.
                    session.query(EmailSummary).filter(EmailSummary.workspace_id == workspace_id).delete()
                existing.org = google_email
                existing.last_synced_at = None
            existing.encrypted_token = encrypted_token
            # A fresh consent is exactly the evidence that the connection is
            # alive again - otherwise it would stay flagged `expired` in the
            # readiness checklist forever after one revocation.
            existing.revoked_at = None
        else:
            session.add(
                Connection(
                    workspace_id=workspace_id, user_id=user_id, provider=provider,
                    org=google_email, repo=label, encrypted_token=encrypted_token,
                )
            )
    session.commit()


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
    from app.services.github_state import github_repository_state

    return GitHubRepositoryOut(
        connection_id=connection.id,
        org=connection.org,
        repo=connection.repo,
        full_name=connection.full_name,
        state=github_repository_state(connection).value,
        paused=connection.paused_at is not None,
        last_synced_at=connection.last_synced_at,
        last_success_at=connection.last_success_at,
        signal_count=session.query(Signal).filter(Signal.connection_id == connection.id).count(),
    )
