from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import (
    admin,
    assistant,
    attention,
    auth,
    briefs,
    calendar,
    channel_ai,
    channel_connections,
    channel_readiness,
    investigations,
    commitments,
    actions,
    goals,
    proactive,
    memory,
    decisions,
    situations,
    hierarchy,
    shared_connections,
    connections,
    connections_ai,
    connections_github_ai,
    connections_microsoft_ai,
    drive,
    findings,
    integrations,
    invites,
    mail,
    meet,
    meeting_prep,
    onboarding,
    runs,
    sync,
    teams,
    workspaces,
    workspace,
)
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.integrations.github_auth import GitHubAuthError
from app.integrations.github_client import GitHubClientError
from app.integrations.google_auth import GoogleAuthError
from app.integrations.graph_client import GraphError
from app.integrations.microsoft_auth import MicrosoftAuthError
from app.integrations.slack_auth import SlackAuthError
from app.integrations.slack_client import SlackClientError
from app.integrations.zoom_auth import ZoomAuthError
from app.integrations.zoom_client import ZoomError

logger = get_logger("sentinel.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("sentinel_api_starting")
    yield
    logger.info("sentinel_api_stopping")


app = FastAPI(title="Sentinel AI", version="0.1.0", lifespan=lifespan)


# --- provider failures are not Sentinel failures ---------------------------
#
# A revoked token or a provider outage is the single most likely thing to go
# wrong in production, and until now every one of them surfaced as a generic
# 500: "Something went wrong on Sentinel's side - the details have been
# logged." That is both wrong and useless. Nothing went wrong on Sentinel's
# side, and the one thing the person could actually do about it - reconnect
# the account - went unsaid.
#
# Registered once here rather than wrapped around ~10 call sites across
# calendar, mail, drive, workspace and integrations, because the next route to
# call a provider would otherwise have to remember, and would not.
#
# 502 rather than 500: the request was fine, an upstream dependency was not.
_PROVIDER_AUTH_ERRORS: tuple[type[Exception], ...] = (
    GoogleAuthError,
    MicrosoftAuthError,
    ZoomAuthError,
    SlackAuthError,
    GitHubAuthError,
)
_PROVIDER_API_ERRORS: tuple[type[Exception], ...] = (
    GraphError,
    SlackClientError,
    GitHubClientError,
    ZoomError,
)


async def handle_provider_auth_error(request, exc):
    """The connection needs re-authorizing. Say so."""
    logger.warning(
        "provider_auth_failed", path=str(request.url.path), error=str(exc)[:200],
        kind=type(exc).__name__,
    )
    return JSONResponse(
        status_code=502,
        content={
            "detail": (
                "That connection needs to be reconnected - its authorization has "
                "expired or was revoked. Open Connections to reconnect it."
            )
        },
    )


async def handle_provider_api_error(request, exc):
    """The provider refused or was unreachable. Not our bug, and not fatal."""
    logger.warning(
        "provider_call_failed", path=str(request.url.path), error=str(exc)[:200],
        kind=type(exc).__name__,
    )
    return JSONResponse(
        status_code=502,
        content={"detail": "The provider could not be reached just now - please try again in a moment."},
    )


# Registered one class at a time, deliberately. Starlette resolves a handler by
# walking type(exc).__mro__ and looking each class up as a dict key, so passing
# a TUPLE registers the tuple itself as the key and the handler never fires -
# silently, which is the worst way for error handling to be wrong.
for _exc in _PROVIDER_AUTH_ERRORS:
    app.add_exception_handler(_exc, handle_provider_auth_error)
for _exc in _PROVIDER_API_ERRORS:
    app.add_exception_handler(_exc, handle_provider_api_error)


@app.middleware("http")
async def catch_unhandled_errors(request, call_next):
    """Turn any unhandled exception into a clean JSON 500 *inside* the
    middleware stack. Starlette's own catch-all Exception handler runs
    OUTSIDE CORSMiddleware, so before this existed an unhandled crash
    produced a 500 with no Access-Control-Allow-Origin header - the browser
    then reported it as a CORS failure, completely masking the real error
    (confirmed real: a Gmail body fetch for a deleted message surfaced as
    "blocked by CORS policy" in the UI). Registered before Session/CORS so
    it sits innermost - its response passes back out through CORSMiddleware
    and gets the headers.
    """
    try:
        return await call_next(request)
    except Exception:
        logger.exception("unhandled_api_error", path=str(request.url.path))
        return JSONResponse(
            status_code=500,
            content={"detail": "Something went wrong on Sentinel's side - the details have been logged."},
        )


# Required by authlib's OAuth client to hold state/nonce between an OAuth
# redirect and its callback (both /auth/{provider}/login and
# /integrations/google/connect use this) - not a general-purpose session
# store, our own auth is otherwise stateless JWT (api/deps.py's get_current_user).
app.add_middleware(SessionMiddleware, secret_key=get_settings().session_secret_key)

# The frontend runs on a different origin from the API in every environment, so
# CORS is configuration rather than a dev-only hack. `cors_origins` is an
# explicit allow-list - never "*", which would be incompatible with
# allow_credentials and would let any site call the API with a user's session.
#
# The defaults cover local development only: 5173 is the original Vite app and
# 5273/5274 the new one, which coexist during the frontend migration.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(attention.router)
app.include_router(meeting_prep.router)
app.include_router(onboarding.router)
app.include_router(connections.router)
app.include_router(runs.router)
app.include_router(sync.router)
app.include_router(briefs.router)
app.include_router(findings.router)
app.include_router(admin.router)
app.include_router(workspaces.router)
app.include_router(hierarchy.router)
app.include_router(shared_connections.router)
app.include_router(teams.router)
app.include_router(channel_connections.router)
app.include_router(channel_readiness.router)
app.include_router(channel_ai.router)
app.include_router(invites.router)
app.include_router(integrations.router)
app.include_router(assistant.router)
app.include_router(investigations.router)
app.include_router(proactive.router)
app.include_router(commitments.router)
app.include_router(goals.router)
app.include_router(actions.router)
app.include_router(mail.router)
app.include_router(calendar.router)
app.include_router(connections_ai.router)
app.include_router(connections_github_ai.router)
app.include_router(connections_microsoft_ai.router)
app.include_router(drive.router)
app.include_router(meet.router)
app.include_router(memory.router)
app.include_router(memory.channel_router)
app.include_router(decisions.router)
app.include_router(decisions.channel_router)
app.include_router(situations.router)
app.include_router(workspace.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
