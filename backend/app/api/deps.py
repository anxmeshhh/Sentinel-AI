import uuid
from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.bootstrap import get_or_create_default_workspace
from app.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_workspace_id(session: Session = Depends(get_db)) -> uuid.UUID:
    """Phase 1: resolves to the single implicit workspace (see core/bootstrap.py).
    Phase 2 swaps this for real auth-derived resolution without touching
    anything downstream of it - every route and repository already takes a
    workspace_id, not a "the" workspace.
    """
    return get_or_create_default_workspace(session).id
