"""Phase 1 has no auth/multi-tenant onboarding yet, so there is exactly one
implicit workspace. This is the single seam Phase 2 replaces with real
auth-derived workspace resolution (IA.md §3) without touching any route,
repository, or agent code above it.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workspace import Workspace, WorkspaceKind

DEFAULT_WORKSPACE_SLUG = "default"


def get_or_create_default_workspace(session: Session) -> Workspace:
    workspace = session.execute(select(Workspace).where(Workspace.slug == DEFAULT_WORKSPACE_SLUG)).scalar_one_or_none()
    if workspace is None:
        workspace = Workspace(name="Default Organization", slug=DEFAULT_WORKSPACE_SLUG, kind=WorkspaceKind.ORGANIZATION)
        session.add(workspace)
        session.commit()
        session.refresh(workspace)
    return workspace
