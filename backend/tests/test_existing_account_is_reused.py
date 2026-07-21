"""An existing Sentinel account must be recognised, never duplicated.

The user's requirement: "any user who already has a registered Sentinel
account can be added/invited to Team Workspaces, Groups, and Channels by an
authorized Admin. The system should recognize their existing Sentinel
account instead of creating a duplicate user."

The guarantee is structural rather than defensive - no invite path
constructs a User at all - so these tests are written to fail loudly if
someone ever adds one.
"""

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.invite import WorkspaceInvite
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.auth import AuthError, create_user_with_password, find_or_create_oauth_user
from app.services.invites import accept_invite


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


@pytest.fixture
def env(session):
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    admin = User(email="admin@acme.test", name="Admin")
    existing = User(email="existing@elsewhere.test", name="Existing Person", email_verified=True)
    session.add_all([workspace, admin, existing])
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=admin.id, role=Role.ORG_ADMIN))

    team = Team(workspace_id=workspace.id, name="development", slug="dev")
    session.add(team)
    session.commit()
    return {"workspace": workspace, "admin": admin, "existing": existing, "team": team}


def _invite(session, env, *, team_id=None):
    invite = WorkspaceInvite(
        workspace_id=env["workspace"].id, team_id=team_id, token=uuid.uuid4().hex,
        role=Role.EMPLOYEE, created_by_user_id=env["admin"].id,
    )
    session.add(invite)
    session.commit()
    return invite


def test_accepting_a_workspace_invite_reuses_the_existing_account(session, env):
    before = session.execute(select(User)).scalars().all()

    accept_invite(session, _invite(session, env), env["existing"])

    after = session.execute(select(User)).scalars().all()
    assert len(after) == len(before)  # no new User row

    membership = session.query(Membership).filter_by(
        workspace_id=env["workspace"].id, user_id=env["existing"].id
    ).one()
    assert membership.user_id == env["existing"].id  # the same account, not a copy


def test_accepting_a_channel_invite_joins_both_workspace_and_channel(session, env):
    accept_invite(session, _invite(session, env, team_id=env["team"].id), env["existing"])

    assert session.query(Membership).filter_by(workspace_id=env["workspace"].id, user_id=env["existing"].id).count() == 1
    assert session.query(TeamMembership).filter_by(team_id=env["team"].id, user_id=env["existing"].id).count() == 1
    assert session.execute(select(User).where(User.email == "existing@elsewhere.test")).scalars().all().__len__() == 1


def test_accepting_the_same_invite_twice_does_not_duplicate_membership(session, env):
    invite = _invite(session, env, team_id=env["team"].id)
    accept_invite(session, invite, env["existing"])
    accept_invite(session, invite, env["existing"])

    assert session.query(Membership).filter_by(workspace_id=env["workspace"].id, user_id=env["existing"].id).count() == 1
    assert session.query(TeamMembership).filter_by(team_id=env["team"].id, user_id=env["existing"].id).count() == 1


def test_an_already_promoted_member_keeps_their_channel_role(session, env):
    """Re-accepting must not silently demote a channel admin back to member -
    accept_invite only inserts when absent, never overwrites."""
    session.add(TeamMembership(team_id=env["team"].id, user_id=env["existing"].id, role=ChannelRole.CHANNEL_ADMIN))
    session.commit()

    accept_invite(session, _invite(session, env, team_id=env["team"].id), env["existing"])

    membership = session.query(TeamMembership).filter_by(team_id=env["team"].id, user_id=env["existing"].id).one()
    assert membership.role == ChannelRole.CHANNEL_ADMIN


def test_signing_up_again_with_a_known_email_is_refused(session, env):
    with pytest.raises(AuthError):
        create_user_with_password(session, email="existing@elsewhere.test", name="Impostor", password="hunter22")


def test_google_signin_links_to_the_existing_password_account(session, env):
    """Same person, second door. Matching on email rather than minting a
    second account is what keeps their workspaces and connections attached."""
    user = find_or_create_oauth_user(
        session, provider="google", sub="google-sub-123",
        email="existing@elsewhere.test", name="Existing Person",
    )

    assert user.id == env["existing"].id
    assert user.google_sub == "google-sub-123"
    assert len(session.execute(select(User)).scalars().all()) == 2  # admin + existing, nothing new


def test_the_database_itself_refuses_a_duplicate_email(session, env):
    """Defense in depth: even a future code path that skips every check
    above cannot create the duplicate."""
    session.add(User(email="existing@elsewhere.test", name="Duplicate"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
