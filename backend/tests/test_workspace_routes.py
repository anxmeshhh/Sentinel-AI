"""Workspace creation must actually return a valid response.

Found by end-to-end verification, not by the unit suite: POST /workspaces
returned the ORM Workspace object while WorkspaceOut requires a `role`
field that only exists on Membership. FastAPI raised a
ResponseValidationError on every call, so creating a Group - the entry
point to the whole Groups/Channels feature - returned 500 and had never
worked.

Nothing caught it because the service-layer tests construct workspaces
directly and never exercise the route's response serialization.
"""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.workspaces import create_workspace, list_workspaces
from app.models.base import Base
from app.models.user import User
from app.models.workspace import Membership, Role, WorkspaceKind
from app.schemas.workspace import WorkspaceCreate


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
def user(session):
    u = User(email=f"u-{uuid.uuid4().hex[:6]}@test.local", name="U")
    session.add(u)
    session.commit()
    return u


def test_create_workspace_returns_a_complete_serializable_response(session, user):
    """The regression: every field WorkspaceOut declares must be present and
    correctly typed, or FastAPI 500s during response serialization."""
    out = create_workspace(payload=WorkspaceCreate(name="Acme"), session=session, user=user)

    assert out.name == "Acme"
    assert out.kind == WorkspaceKind.ORGANIZATION.value
    assert out.role == Role.ORG_ADMIN.value  # the field that was missing
    assert out.is_demo is False
    assert isinstance(out.id, uuid.UUID)
    assert out.slug


def test_creator_becomes_org_admin_member(session, user):
    out = create_workspace(payload=WorkspaceCreate(name="Acme"), session=session, user=user)

    membership = session.query(Membership).filter_by(workspace_id=out.id, user_id=user.id).one()
    assert membership.role == Role.ORG_ADMIN


def test_created_workspace_appears_in_the_users_list(session, user):
    """What the frontend refresh reads after creating - if this were empty,
    the dashboard would resolve `active` to null and hang."""
    created = create_workspace(payload=WorkspaceCreate(name="Acme"), session=session, user=user)

    listed = list_workspaces(session=session, user=user)
    assert any(w.id == created.id for w in listed)
    assert all(w.role for w in listed)  # role populated on every row


def test_two_workspaces_get_distinct_slugs(session, user):
    a = create_workspace(payload=WorkspaceCreate(name="Acme"), session=session, user=user)
    b = create_workspace(payload=WorkspaceCreate(name="Acme"), session=session, user=user)
    assert a.slug != b.slug
