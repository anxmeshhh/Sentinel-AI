from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import admin, assistant, auth, briefs, connections, findings, runs, workspaces
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

# Required by authlib's OAuth client to hold state/nonce between the
# /auth/{provider}/login redirect and the /auth/{provider}/callback - not a
# general-purpose session store, nothing else in the app uses it (auth is
# otherwise stateless JWT, per api/deps.py's get_current_user).
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
app.include_router(assistant.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
