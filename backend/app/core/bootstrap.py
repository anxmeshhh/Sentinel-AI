"""Phase 1 has no real auth/signup yet, so there is exactly one implicit user
and (as of Phase 1.5) exactly two implicit workspaces for that user: an
Organization workspace (Phase 1's original scope) and a Personal workspace
(IA.md's "every user always has exactly one Personal Workspace").

This is the single seam Phase 2 replaces with real auth-derived user/workspace
resolution (IA.md §3) without touching any route, repository, or agent code
above it - everything downstream already takes a `workspace_id`, never "the"
workspace.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind

DEFAULT_ORG_WORKSPACE_SLUG = "default"
DEFAULT_PERSONAL_WORKSPACE_SLUG = "default-personal"
DEFAULT_USER_EMAIL = "you@sentinel.local"


def get_or_create_default_user(session: Session) -> User:
    user = session.execute(select(User).where(User.email == DEFAULT_USER_EMAIL)).scalar_one_or_none()
    if user is None:
        user = User(email=DEFAULT_USER_EMAIL, name="Default User")
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


def get_or_create_default_workspace(session: Session) -> Workspace:
    """The Organization workspace from Phase 1. Name kept for backward
    compatibility with existing callers/tests."""
    return _get_or_create_workspace(
        session,
        slug=DEFAULT_ORG_WORKSPACE_SLUG,
        name="Default Organization",
        kind=WorkspaceKind.ORGANIZATION,
    )


def get_or_create_personal_workspace(session: Session) -> Workspace:
    """New in Phase 1.5: a second, real workspace of a different kind for the
    same user - this is what proves the workspace-scoping architecture
    actually generalizes, not just a single hardcoded tenant."""
    return _get_or_create_workspace(
        session,
        slug=DEFAULT_PERSONAL_WORKSPACE_SLUG,
        name="Personal",
        kind=WorkspaceKind.PERSONAL,
    )


def _get_or_create_workspace(session: Session, *, slug: str, name: str, kind: WorkspaceKind) -> Workspace:
    workspace = session.execute(select(Workspace).where(Workspace.slug == slug)).scalar_one_or_none()
    if workspace is not None:
        return workspace

    user = get_or_create_default_user(session)
    workspace = Workspace(name=name, slug=slug, kind=kind)
    session.add(workspace)
    session.flush()  # assign workspace.id for the membership row below

    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.ORG_ADMIN))
    session.commit()
    session.refresh(workspace)
    return workspace
