import uuid
from collections.abc import Generator

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.bootstrap import get_or_create_default_workspace
from app.db.session import SessionLocal
from app.models.workspace import Workspace


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_workspace_id(
    session: Session = Depends(get_db),
    x_workspace_id: str | None = Header(default=None),
) -> uuid.UUID:
    """Phase 1.5: the frontend's workspace switcher sends `X-Workspace-Id` for
    whichever workspace (Personal/Organization) is active; falls back to the
    original default Organization workspace if the header is absent, so
    every Phase 1 caller keeps working unchanged.

    Still no real authorization check here - Phase 2's RBAC is what makes
    this "does this user actually have access to this workspace" instead of
    "does this workspace id exist at all." Tracked in PHASES.md.
    """
    if x_workspace_id:
        try:
            workspace_uuid = uuid.UUID(x_workspace_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="X-Workspace-Id must be a valid UUID")
        if session.get(Workspace, workspace_uuid) is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return workspace_uuid

    return get_or_create_default_workspace(session).id
