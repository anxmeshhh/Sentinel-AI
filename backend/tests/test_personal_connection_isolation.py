"""Personal connections must never become reachable by anyone else.

The user's rule: "If I connect my personal Gmail and later join a company
Workspace, my Gmail must NOT suddenly become available to that company."

These tests attempt the actual leak paths rather than asserting the happy
case. Each one is written as an attack.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.channel_connections import assign_connection
from app.api.routes.invites import create_workspace_invite
from app.api.routes.teams import create_team
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.schemas.channel_connection import ChannelConnectionCreate
from app.schemas.invite import InviteCreate
from app.schemas.team import TeamCreate


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
    """A user with a personal Gmail connection, plus an unrelated company
    workspace they also belong to."""
    owner = User(email="owner@personal.test", name="Owner")
    colleague = User(email="colleague@acme.test", name="Colleague")
    session.add_all([owner, colleague])
    session.flush()

    personal = Workspace(name="Personal", slug=f"personal-{owner.id}", kind=WorkspaceKind.PERSONAL)
    company = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add_all([personal, company])
    session.flush()

    session.add(Membership(workspace_id=personal.id, user_id=owner.id, role=Role.ORG_ADMIN))
    session.add(Membership(workspace_id=company.id, user_id=owner.id, role=Role.ORG_ADMIN))
    session.add(Membership(workspace_id=company.id, user_id=colleague.id, role=Role.ORG_ADMIN))

    personal_gmail = Connection(
        workspace_id=personal.id, user_id=owner.id, provider=Provider.GMAIL,
        org="owner@gmail.com", repo="gmail", encrypted_token="personal-secret",
    )
    session.add(personal_gmail)

    company_channel = Team(workspace_id=company.id, name="general", slug="general")
    session.add(company_channel)
    session.flush()
    session.add(TeamMembership(team_id=company_channel.id, user_id=owner.id, role=ChannelRole.CHANNEL_ADMIN))
    session.add(TeamMembership(team_id=company_channel.id, user_id=colleague.id, role=ChannelRole.CHANNEL_ADMIN))
    session.commit()

    return {
        "owner": owner, "colleague": colleague, "personal": personal, "company": company,
        "personal_gmail": personal_gmail, "company_channel": company_channel,
    }


def test_personal_connection_cannot_be_assigned_to_a_company_channel(session, env):
    """The headline guarantee: joining a company must not expose personal mail."""
    with pytest.raises(HTTPException) as exc_info:
        assign_connection(
            team_id=env["company_channel"].id,
            payload=ChannelConnectionCreate(connection_id=env["personal_gmail"].id),
            session=session, user=env["owner"],
        )
    assert exc_info.value.status_code == 404


def test_personal_workspace_cannot_be_invited_into(session, env):
    """ATTACK: invite someone into the Personal workspace, and every personal
    connection inside it becomes assignable to channels they can reach.

    A user who clicks 'Invite' on something labelled *Personal* is not
    consenting to share their inbox - the label promises the opposite."""
    with pytest.raises(HTTPException) as exc_info:
        create_workspace_invite(
            workspace_id=env["personal"].id,
            payload=InviteCreate(role="employee"),
            session=session, user=env["owner"],
        )
    assert exc_info.value.status_code == 400


def test_personal_workspace_cannot_contain_channels(session, env):
    """ATTACK: a channel inside the Personal workspace passes the
    same-workspace check, so personal connections become assignable to it.
    Harmless while the workspace has one member - and a leak the moment it
    doesn't. Removing the surface entirely is the durable fix."""
    with pytest.raises(HTTPException) as exc_info:
        create_team(
            workspace_id=env["personal"].id,
            payload=TeamCreate(name="secret"),
            session=session, user=env["owner"],
        )
    assert exc_info.value.status_code == 400


def test_company_connections_still_work_normally(session, env):
    """The isolation must not break legitimate workspace sharing."""
    company_github = Connection(
        workspace_id=env["company"].id, user_id=env["owner"].id, provider=Provider.GITHUB,
        org="acme", repo="api", encrypted_token="company-token",
    )
    session.add(company_github)
    session.commit()

    out = assign_connection(
        team_id=env["company_channel"].id,
        payload=ChannelConnectionCreate(connection_id=company_github.id),
        session=session, user=env["owner"],
    )
    assert out.connection_id == company_github.id


def test_leaving_a_workspace_does_not_touch_personal_connections(session, env):
    """"If I leave the Workspace, my personal Connections remain mine.\""""
    membership = session.query(Membership).filter_by(
        workspace_id=env["company"].id, user_id=env["owner"].id
    ).one()
    session.delete(membership)
    session.commit()

    survivor = session.get(Connection, env["personal_gmail"].id)
    assert survivor is not None
    assert survivor.workspace_id == env["personal"].id
