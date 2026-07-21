"""Phase 3a: Channel roles + RBAC enforcement.

Exercises the real deps.py role-checking helpers and the invite
role-escalation guard against a real (in-memory) database, not mocks -
this is security-sensitive code, worth verifying against actual queries
rather than trusting the logic by inspection alone.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import require_channel_role, require_workspace_role
from app.api.routes.invites import _create_invite
from app.models.base import Base
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.invite import InviteCreate

from tests.hierarchy_helpers import make_group


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


def _make_user(session: Session, email: str) -> User:
    user = User(email=email, name=email)
    session.add(user)
    session.flush()
    return user


def _make_workspace_with_member(session: Session, user: User, role: Role) -> Workspace:
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(workspace)
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=role))
    session.commit()
    return workspace


def _make_team_with_member(session: Session, workspace: Workspace, user: User, channel_role: ChannelRole) -> Team:
    team = Team(workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, name="development", slug=f"dev-{uuid.uuid4().hex[:8]}")
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=user.id, role=channel_role))
    session.commit()
    return team


def test_require_workspace_role_allows_matching_role(session):
    user = _make_user(session, "admin@acme.test")
    workspace = _make_workspace_with_member(session, user, Role.ORG_ADMIN)
    membership = require_workspace_role(session, user, workspace.id, allowed=[Role.ORG_ADMIN, Role.SUPER_ADMIN])
    assert membership.role == Role.ORG_ADMIN


def test_require_workspace_role_rejects_wrong_role(session):
    user = _make_user(session, "guest@acme.test")
    workspace = _make_workspace_with_member(session, user, Role.GUEST)
    with pytest.raises(HTTPException) as exc_info:
        require_workspace_role(session, user, workspace.id, allowed=[Role.ORG_ADMIN, Role.SUPER_ADMIN])
    assert exc_info.value.status_code == 403


def test_require_channel_role_allows_channel_admin(session):
    user = _make_user(session, "lead@acme.test")
    workspace = _make_workspace_with_member(session, user, Role.EMPLOYEE)
    team = _make_team_with_member(session, workspace, user, ChannelRole.CHANNEL_ADMIN)
    membership = require_channel_role(session, user, team.id, allowed=[ChannelRole.CHANNEL_ADMIN])
    assert membership.role == ChannelRole.CHANNEL_ADMIN


def test_require_channel_role_rejects_plain_member(session):
    user = _make_user(session, "member@acme.test")
    workspace = _make_workspace_with_member(session, user, Role.EMPLOYEE)
    team = _make_team_with_member(session, workspace, user, ChannelRole.CHANNEL_MEMBER)
    with pytest.raises(HTTPException) as exc_info:
        require_channel_role(session, user, team.id, allowed=[ChannelRole.CHANNEL_ADMIN])
    assert exc_info.value.status_code == 403


def test_require_channel_role_lets_org_admin_bypass_channel_membership(session):
    """A Workspace org_admin can manage any Channel (Group Owner/Admin has
    full control per the spec) even with no TeamMembership row at all."""
    user = _make_user(session, "org-admin@acme.test")
    workspace = _make_workspace_with_member(session, user, Role.ORG_ADMIN)
    team = Team(workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, name="marketing", slug="mkt")
    session.add(team)
    session.commit()

    require_channel_role(session, user, team.id, allowed=[ChannelRole.CHANNEL_ADMIN])  # must not raise


def test_require_channel_role_404s_for_nonmember_non_admin(session):
    """A plain workspace employee with no TeamMembership row gets 404
    (matches require_workspace_membership's "don't confirm existence to a
    non-member" convention), not a 403 that would leak the team's existence.
    """
    user = _make_user(session, "outsider@acme.test")
    workspace = _make_workspace_with_member(session, user, Role.EMPLOYEE)
    team = Team(workspace_id=workspace.id, group_id=make_group(session, workspace.id).id, name="marketing", slug="mkt2")
    session.add(team)
    session.commit()

    with pytest.raises(HTTPException) as exc_info:
        require_channel_role(session, user, team.id, allowed=[ChannelRole.CHANNEL_ADMIN])
    assert exc_info.value.status_code == 404


def test_invite_cannot_grant_role_above_callers_own(session):
    """Confirmed real bug found while building this: previously nothing
    stopped a Guest from minting an invite granting org_admin."""
    user = _make_user(session, "guest2@acme.test")
    workspace = _make_workspace_with_member(session, user, Role.GUEST)
    membership = session.query(Membership).filter_by(workspace_id=workspace.id, user_id=user.id).one()

    payload = InviteCreate(role="org_admin")
    with pytest.raises(HTTPException) as exc_info:
        _create_invite(session, workspace_id=workspace.id, team_id=None, payload=payload, user=user, caller_membership=membership)
    assert exc_info.value.status_code == 403


def test_invite_can_grant_role_at_or_below_callers_own(session):
    user = _make_user(session, "org-admin2@acme.test")
    workspace = _make_workspace_with_member(session, user, Role.ORG_ADMIN)
    membership = session.query(Membership).filter_by(workspace_id=workspace.id, user_id=user.id).one()

    payload = InviteCreate(role="employee")
    invite = _create_invite(session, workspace_id=workspace.id, team_id=None, payload=payload, user=user, caller_membership=membership)
    assert invite.role == Role.EMPLOYEE
