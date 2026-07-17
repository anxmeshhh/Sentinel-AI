import uuid
from collections.abc import Generator

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.auth import InvalidTokenError, decode_access_token
from app.core.bootstrap import get_or_create_default_workspace
from app.db.session import SessionLocal
from app.models.user import User
from app.models.workspace import Workspace

_bearer_scheme = HTTPBearer(auto_error=False)


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


def get_current_user(
    session: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    """Standalone for now - not yet required by any existing route (those
    still resolve through get_workspace_id's implicit-user model). This is
    the seam real per-route auth enforcement hangs off once workspace CRUD
    and RBAC (IA.md v2 §8.2) actually need "who is asking," not just
    "which workspace." /auth/me is the first real consumer.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user
