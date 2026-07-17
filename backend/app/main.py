from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, assistant, briefs, connections, findings, runs, workspaces
from app.core.logging import configure_logging, get_logger

logger = get_logger("sentinel.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("sentinel_api_starting")
    yield
    logger.info("sentinel_api_stopping")


app = FastAPI(title="Sentinel AI", version="0.1.0", lifespan=lifespan)

# Dev-only CORS: the Vite dev server runs on a different origin. Tighten this
# to the deployed frontend's real origin before anything but local dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
