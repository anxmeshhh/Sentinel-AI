"""Phase 2r: the seeded Explore workspace and persona onboarding.

The properties that matter: the demo is real data flowing through real
detectors (not scripted output), it needs no credentials, re-entry re-seeds
rather than duplicates, and it can never perform a real external write.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.attention_item import AttentionItem, AttentionType
from app.models.base import Base
from app.models.connection import Connection
from app.models.signal import Signal, SignalType
from app.models.user import Persona, User
from app.models.workspace import Membership, Workspace, WorkspaceKind
from app.services.attention_engine import list_attention
from app.services.demo_data import create_demo_workspace, get_demo_workspace
from app.services.orchestrator import _execute_demo_read_tool, _is_demo_workspace, execute_planned_action


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
    u = User(email=f"demo-{uuid.uuid4().hex[:6]}@test.local", name="Demo User")
    session.add(u)
    session.commit()
    return u


def test_demo_workspace_seeds_all_four_sources(session, user):
    workspace, count = create_demo_workspace(session, user)

    assert workspace.is_demo is True
    assert count > 0
    types = {
        s.type
        for s in session.execute(select(Signal).where(Signal.workspace_id == workspace.id)).scalars()
    }
    assert types == {SignalType.EMAIL, SignalType.CALENDAR_EVENT, SignalType.DRIVE_FILE, SignalType.PR}
    # The user is a member, so it shows up in their workspace switcher.
    assert session.execute(
        select(Membership).where(Membership.workspace_id == workspace.id, Membership.user_id == user.id)
    ).scalar_one_or_none() is not None


def test_demo_attention_is_really_detected_not_scripted(session, user):
    """The demo list must come from the real engine running over seeded
    facts - including correctly *rejecting* the noise we planted (a read
    email, a promotional email, a merged PR)."""
    workspace, _ = create_demo_workspace(session, user)
    items = list_attention(session, workspace.id)

    titles = [i.title for i in items]
    assert any("Contract question" in t for t in titles)  # starred + unread
    assert any("Product Demo" in t for t in titles)  # meeting within 24h
    assert not any("roadmap doc" in t for t in titles)  # read -> correctly ignored
    assert not any("50% off" in t for t in titles)  # promotional -> correctly ignored
    assert not any("Upgrade dependencies" in t for t in titles)  # merged PR -> correctly ignored

    types = {i.type for i in items}
    assert AttentionType.UPCOMING_MEETING in types
    assert AttentionType.IMPORTANT_EMAIL in types


def test_reentering_demo_reseeds_instead_of_duplicating(session, user):
    workspace_1, count_1 = create_demo_workspace(session, user)
    workspace_2, count_2 = create_demo_workspace(session, user)

    assert workspace_1.id == workspace_2.id  # same workspace, not a second one
    assert count_1 == count_2
    total_signals = len(session.execute(select(Signal).where(Signal.workspace_id == workspace_1.id)).scalars().all())
    assert total_signals == count_1  # re-seed replaced, didn't stack

    assert len(session.execute(select(Workspace).where(Workspace.is_demo.is_(True))).scalars().all()) == 1


def test_demo_timestamps_are_relative_to_now(session, user):
    """A fixed-date demo reads as dead. The meeting must always be a few
    hours out, whenever the demo is run."""
    workspace, _ = create_demo_workspace(session, user)
    meeting = session.execute(
        select(Signal).where(Signal.workspace_id == workspace.id, Signal.external_id == "demo-evt-1")
    ).scalar_one()

    start = datetime.fromisoformat(meeting.payload["start"])
    hours_away = (start - datetime.now(timezone.utc)).total_seconds() / 3600
    assert 2 < hours_away < 4


def test_demo_tools_read_seeded_data_without_credentials(session, user):
    workspace, _ = create_demo_workspace(session, user)
    assert _is_demo_workspace(session, workspace.id) is True

    emails = _execute_demo_read_tool(session, workspace.id, "search_emails", {"keywords": "contract"})
    assert len(emails) >= 1
    assert "Contract question" in emails[0]["subject"]

    body = _execute_demo_read_tool(session, workspace.id, "read_email_body", {"message_id": "demo-mail-1"})
    assert "clause 7.2" in body["body"]

    files = _execute_demo_read_tool(session, workspace.id, "search_drive", {"keywords": "proposal"})
    assert any("Proposal" in f["name"] for f in files)

    content = _execute_demo_read_tool(session, workspace.id, "read_drive_file", {"file_id": "demo-doc-1"})
    assert "30 days" in content["content"]


def test_demo_tools_are_scoped_to_their_own_workspace(session, user):
    """Demo tool reads must not leak across workspaces."""
    workspace, _ = create_demo_workspace(session, user)
    other = Workspace(name="Other", slug="other-ws", kind=workspace.kind)
    session.add(other)
    session.commit()

    assert _execute_demo_read_tool(session, other.id, "search_emails", {}) == []
    assert "error" in _execute_demo_read_tool(session, other.id, "read_email_body", {"message_id": "demo-mail-1"})


def test_demo_connections_hold_no_usable_credentials(session, user):
    workspace, _ = create_demo_workspace(session, user)
    for connection in session.execute(select(Connection).where(Connection.workspace_id == workspace.id)).scalars():
        assert connection.encrypted_token  # shape is valid...
        assert connection.org in {"you@brightloop.io", "brightloop"}  # ...but it's demo-only


def test_demo_workspace_refuses_real_external_writes(session, user):
    workspace, _ = create_demo_workspace(session, user)
    with pytest.raises(ValueError, match="demo workspace"):
        execute_planned_action(
            session, workspace.id, "create_calendar_event",
            {"title": "Test", "start": "2026-01-01T10:00:00+00:00", "end": "2026-01-01T11:00:00+00:00"},
        )


def test_non_demo_workspace_is_unaffected(session, user):
    """The demo branch must be inert for every real workspace."""
    real = Workspace(name="Real", slug="real-ws", kind=WorkspaceKind.PERSONAL)
    session.add(real)
    session.commit()

    assert _is_demo_workspace(session, real.id) is False


def test_persona_enum_covers_every_onboarding_option():
    assert {p.value for p in Persona} == {"individual", "developer", "team", "business", "explorer"}
