"""'Sync Now' - see app/services/sync_now.py for what this actually runs and
why it's synchronous rather than another Celery dispatch."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.api.routes.workspace import SERVICE_PROVIDERS
from app.models.user import User
from app.services.sync_now import run_full_sync

router = APIRouter(prefix="/sync", tags=["sync"])


class SyncResult(BaseModel):
    status: Literal["success", "partial", "failed", "no_connections"]
    connections_checked: int
    connections_failed: int
    signals_ingested: int
    synced_at: datetime
    errors: list[str] = []


@router.post("", response_model=SyncResult)
def sync_now(
    service: str | None = None,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> SyncResult:
    """Full sync by default. `?service=gmail` narrows the provider pull to
    one service's connections - a provider page's own Sync Now - while the
    downstream pipeline still runs for the whole workspace (see
    run_full_sync's docstring for why that's still correct)."""
    providers = None
    if service is not None:
        providers = SERVICE_PROVIDERS.get(service)
        if providers is None:
            raise HTTPException(status_code=404, detail=f"Unknown workspace service: {service}")

    outcome = run_full_sync(session, workspace_id, user.id, providers=providers)
    return SyncResult(**outcome.__dict__)
