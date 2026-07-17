import uuid
from collections.abc import Generator

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import InvalidTokenError, decode_access_token
from app.core.bootstrap import provision_personal_workspace_for_user
from app.db.session import SessionLocal
from app.models.user import User
from app.models.workspace import Membership

_bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    session: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
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


def require_workspace_membership(session: Session, user: User, workspace_id: uuid.UUID) -> Membership:
    """404, not 403, for a workspace that exists but isn't the caller's -
    doesn't confirm existence to a non-member. Shared by get_workspace_id
    (header-based, for the "currently active workspace" pattern) and any
    route that takes an explicit workspace_id in its path (Team CRUD,
    invites) instead.
    """
    membership = session.execute(
        select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user.id)
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return membership


def get_workspace_id(
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    x_workspace_id: str | None = Header(default=None),
) -> uuid.UUID:
    """Phase 1.6: real auth required (get_current_user) - the anonymous
    bootstrap-workspace fallback from Phase 1/1.5 is gone. The frontend's
    workspace switcher sends `X-Workspace-Id` for whichever workspace is
    active; membership is checked, not just existence, so one user can never
    address another's workspace by guessing its id. No header defaults to
    the caller's own Personal workspace.
    """
    if x_workspace_id:
        try:
            workspace_uuid = uuid.UUID(x_workspace_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="X-Workspace-Id must be a valid UUID")
        require_workspace_membership(session, user, workspace_uuid)
        return workspace_uuid

    return provision_personal_workspace_for_user(session, user).id
