from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import (
    admin,
    assistant,
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
