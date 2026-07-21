"""#4: the privacy boundaries, as standing attack tests.

Each test attempts an actual breach and asserts it fails safely. Written
against the same scenario the live MySQL probe used (18/18 passed there),
kept here so every boundary is re-checked on every commit rather than only
when someone remembers to run a probe.

The spec's four questions map directly:
- Q1: can Personal Gmail leak into a company workspace?
- Q2: can Channel A access Channel B's resources?
- Q3: can a Member perform an Admin action?
- Q4: what happens after a connection is revoked?
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import require_workspace_membership
from app.api.routes.channel_connections import add_allowed_resource, assign_connection
from app.api.routes.channel_readiness import add_channel_requirement, channel_roster_readiness, my_channel_readiness
from app.api.routes.invites import create_workspace_invite
from app.api.routes.teams import add_team_member, create_team, delete_team, update_team
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.repositories.connections import ConnectionRepository
from app.schemas.channel_connection import ChannelConnectionCreate, ChannelConnectionResourceCreate
from app.schemas.channel_readiness import ChannelRequirementCreate
from app.schemas.invite import InviteCreate
from app.schemas.team import TeamCreate, TeamMemberAdd, TeamUpdate
from app.services.channel_connections import is_resource_allowed
from app.services.channel_feed import build_channel_feed
from app.services.orchestrator import _get_connection

NOW = datetime.now(timezone.utc)


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
    """Owner with a private Personal Gmail, plus a company they and a plain
    Employee colleague both belong to. Two channels in the company, colleague
    is a plain member of channel A only."""
    owner = User(email="owner@atk.test", name="Owner")
    colleague = User(email="colleague@atk.test", name="Colleague")
    session.add_all([owner, colleague])
    session.flush()

    personal = Workspace(name="Personal", slug=f"p-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.PERSONAL)
    company = Workspace(name="Company", slug=f"c-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add_all([personal, company])
    session.flush()
    session.add_all([
        Membership(workspace_id=personal.id, user_id=owner.id, role=Role.ORG_ADMIN),
        Membership(workspace_id=company.id, user_id=owner.id, role=Role.ORG_ADMIN),
        Membership(workspace_id=company.id, user_id=colleague.id, role=Role.EMPLOYEE),
    ])
    klass = WorkspaceClass(workspace_id=company.id, name="Dev", slug=f"d-{uuid.uuid4().hex[:6]}")
    session.add(klass)
    session.flush()
    group = Group(class_id=klass.id, name="BE", slug=f"b-{uuid.uuid4().hex[:6]}")
    session.add(group)
    session.flush()
    personal_gmail = Connection(
        workspace_id=personal.id, user_id=owner.id, provider=Provider.GMAIL,
        org="owner@gmail.com", repo="gmail", encrypted_token="personal-secret", last_synced_at=NOW,
    )
    session.add(personal_gmail)
    session.commit()

    chan_a = create_team(workspace_id=company.id, payload=TeamCreate(name="alpha", group_id=group.id), session=session, user=owner)
    chan_b = create_team(workspace_id=company.id, payload=TeamCreate(name="beta", group_id=group.id), session=session, user=owner)
    add_team_member(team_id=chan_a.id, payload=TeamMemberAdd(user_id=colleague.id), session=session, user=owner)

    return {
        "owner": owner, "colleague": colleague, "personal": personal, "company": company,
        "group": group, "personal_gmail": personal_gmail, "chan_a": chan_a, "chan_b": chan_b,
    }


# --- Q1: personal data cannot leak into a company workspace ---------------


def test_personal_connection_cannot_be_assigned_to_a_company_channel(session, env):
    with pytest.raises(HTTPException) as exc:
        assign_connection(
            team_id=env["chan_a"].id,
            payload=ChannelConnectionCreate(connection_id=env["personal_gmail"].id),
            session=session, user=env["owner"],
        )
    assert exc.value.status_code == 404  # not found in this workspace, don't confirm it exists


def test_company_ai_and_repo_are_blind_to_the_personal_connection(session, env):
    assert _get_connection(session, env["company"].id, None, Provider.GMAIL, user_id=env["owner"].id) is None
    assert ConnectionRepository(session, env["company"].id).get_for_user(env["owner"].id, Provider.GMAIL) is None


def test_personal_workspace_cannot_be_invited_into(session, env):
    with pytest.raises(HTTPException) as exc:
        create_workspace_invite(workspace_id=env["personal"].id, payload=InviteCreate(role="employee"), session=session, user=env["owner"])
    assert exc.value.status_code == 400


# --- Q2: one channel cannot reach another channel's resources -------------


def test_channel_a_cannot_reach_channel_b_resources(session, env):
    drive = Connection(
        workspace_id=env["company"].id, user_id=env["owner"].id, provider=Provider.GOOGLE_DRIVE,
        org="owner@c.io", repo="drive", encrypted_token="x", last_synced_at=NOW,
    )
    session.add(drive)
    session.commit()
    cc_b = assign_connection(team_id=env["chan_b"].id, payload=ChannelConnectionCreate(connection_id=drive.id), session=session, user=env["owner"])
    add_allowed_resource(
        team_id=env["chan_b"].id, channel_connection_id=cc_b.id,
        payload=ChannelConnectionResourceCreate(resource_key="secret-doc", resource_label="Secret"),
        session=session, user=env["owner"],
    )

    assert is_resource_allowed(session, env["chan_b"].id, drive.id, "secret-doc") is True
    assert is_resource_allowed(session, env["chan_a"].id, drive.id, "secret-doc") is False
    # A's AI can't see a connection that was only assigned to B.
    assert _get_connection(session, env["company"].id, env["chan_a"].id, Provider.GOOGLE_DRIVE, user_id=env["owner"].id) is None

    session.add(Signal(
        workspace_id=env["company"].id, connection_id=drive.id, type=SignalType.DRIVE_FILE,
        external_id="secret-doc", actor="owner", payload={"title": "Secret", "url": "https://x"}, occurred_at=NOW,
    ))
    session.commit()
    feed_a = build_channel_feed(session, env["chan_a"].id)
    assert feed_a["no_connections"] or feed_a["items"] == []


# --- Q3: a member cannot perform admin actions ----------------------------


@pytest.mark.parametrize(
    "label,attack",
    [
        ("edit", lambda s, e: update_team(team_id=e["chan_a"].id, payload=TeamUpdate(name="hax"), session=s, user=e["colleague"])),
        ("delete", lambda s, e: delete_team(team_id=e["chan_a"].id, session=s, user=e["colleague"])),
        ("declare requirement", lambda s, e: add_channel_requirement(team_id=e["chan_a"].id, payload=ChannelRequirementCreate(provider=Provider.GMAIL), session=s, user=e["colleague"])),
        ("read roster", lambda s, e: channel_roster_readiness(team_id=e["chan_a"].id, session=s, user=e["colleague"])),
        ("add member", lambda s, e: add_team_member(team_id=e["chan_a"].id, payload=TeamMemberAdd(user_id=e["colleague"].id), session=s, user=e["colleague"])),
    ],
)
def test_member_cannot_perform_admin_action(session, env, label, attack):
    with pytest.raises(HTTPException) as exc:
        attack(session, env)
    assert exc.value.status_code == 403, f"member {label} should be forbidden"


# --- Q4: revocation blocks and never leaks credentials --------------------


def test_revoked_connection_becomes_expired_and_blocks(session, env):
    add_channel_requirement(team_id=env["chan_a"].id, payload=ChannelRequirementCreate(provider=Provider.GMAIL), session=session, user=env["owner"])
    gmail = Connection(
        workspace_id=env["company"].id, user_id=env["owner"].id, provider=Provider.GMAIL,
        org="owner@c.io", repo="gmail", encrypted_token="x", last_synced_at=NOW,
    )
    session.add(gmail)
    session.commit()
    assert my_channel_readiness(team_id=env["chan_a"].id, session=session, user=env["owner"]).is_ready is True

    gmail.revoked_at = NOW
    session.commit()
    after = my_channel_readiness(team_id=env["chan_a"].id, session=session, user=env["owner"])
    assert after.is_ready is False
    assert "gmail" in after.blocking_providers

    roster = channel_roster_readiness(team_id=env["chan_a"].id, session=session, user=env["owner"])
    assert all("token" not in str(r.requirements) for r in roster)


# --- Q5: cross-workspace addressing --------------------------------------


def test_colleague_cannot_address_owners_personal_workspace(session, env):
    with pytest.raises(HTTPException) as exc:
        require_workspace_membership(session, env["colleague"], env["personal"].id)
    assert exc.value.status_code == 404
