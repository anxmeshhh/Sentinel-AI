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
    connections,
    connections_ai,
    drive,
    findings,
    integrations,
    invites,
    mail,
    meet,
    meeting_prep,
    onboarding,
    runs,
    teams,
    workspaces,
)
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

logger = get_logger("sentinel.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("sentinel_api_starting")
    yield
    logger.info("sentinel_api_stopping")


app = FastAPI(title="Sentinel AI", version="0.1.0", lifespan=lifespan)


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

# Dev-only CORS: the Vite dev server runs on a different origin. Tighten this
# to the deployed frontend's real origin before anything but local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
app.include_router(briefs.router)
app.include_router(findings.router)
app.include_router(admin.router)
app.include_router(workspaces.router)
app.include_router(teams.router)
app.include_router(channel_connections.router)
app.include_router(channel_ai.router)
app.include_router(invites.router)
app.include_router(integrations.router)
app.include_router(assistant.router)
app.include_router(mail.router)
app.include_router(calendar.router)
app.include_router(connections_ai.router)
app.include_router(drive.router)
app.include_router(meet.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
