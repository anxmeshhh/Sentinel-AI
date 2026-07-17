"""Invite validation + acceptance. A Team invite (team_id set) creates both
the Workspace Membership and the TeamMembership on accept - IA.md v2 §2.4:
"accepting either always creates the Workspace Membership; a Team-scoped one
additionally creates the TeamMembership."
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.invite import WorkspaceInvite
from app.models.team import TeamMembership
from app.models.user import User
from app.models.workspace import Membership


def get_invite_by_token(session: Session, token: str) -> WorkspaceInvite | None:
    return session.execute(select(WorkspaceInvite).where(WorkspaceInvite.token == token)).scalar_one_or_none()


def validate_invite(invite: WorkspaceInvite) -> tuple[bool, str | None]:
    if invite.expires_at and invite.expires_at < datetime.now(timezone.utc):
        return False, "This invite has expired"
    if invite.max_uses is not None and invite.used_count >= invite.max_uses:
        return False, "This invite has already been used"
    return True, None


def accept_invite(session: Session, invite: WorkspaceInvite, user: User) -> None:
    existing = session.execute(
        select(Membership).where(Membership.workspace_id == invite.workspace_id, Membership.user_id == user.id)
    ).scalar_one_or_none()
    if existing is None:
        session.add(Membership(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role))

    if invite.team_id is not None:
        existing_team = session.execute(
            select(TeamMembership).where(TeamMembership.team_id == invite.team_id, TeamMembership.user_id == user.id)
        ).scalar_one_or_none()
        if existing_team is None:
            session.add(TeamMembership(team_id=invite.team_id, user_id=user.id))

    invite.used_count += 1
    session.commit()
