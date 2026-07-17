"""Workspace auto-provisioning for real accounts.

Phase 1/1.5's anonymous single-implicit-user bootstrap is gone as of Phase
1.6 (real auth) - every route now resolves a workspace through a real,
authenticated user's Memberships (api/deps.py's get_workspace_id). This is
the one piece of that story: giving every new account its Personal Workspace
automatically (IA.md v2 §1's "every user always has exactly one").
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind


def provision_personal_workspace_for_user(session: Session, user: User) -> Workspace:
    """Idempotent - safe to call on every login, not just once at signup."""
    slug = f"personal-{user.id}"
    existing = session.execute(select(Workspace).where(Workspace.slug == slug)).scalar_one_or_none()
    if existing is not None:
        return existing

    workspace = Workspace(name="Personal", slug=slug, kind=WorkspaceKind.PERSONAL)
    session.add(workspace)
    session.flush()

    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.ORG_ADMIN))
    session.commit()
    session.refresh(workspace)
    return workspace
