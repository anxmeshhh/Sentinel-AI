"""Investigate This: correlation, and the boundaries it must not cross.

An investigation is the most data-hungry feature in Sentinel - its whole job
is to reach outward from one item and pull in everything related. That makes
it the feature where an authorization mistake would be widest, so most of
these tests are about what it must *not* reach.

The property that makes that tractable: the authorization scope is decided
before any retrieval runs, and every query is filtered to it. So the tests
below don't check that unauthorized results were removed afterwards - they
check that a query could never have returned them.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import SharedConnection, SharedScope
from app.models.signal import Signal, SignalType
from app.models.team import ChannelRole, Team, TeamMembership
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.investigation import (
    MAX_EVIDENCE,
    NotAuthorized,
    channel_scope,
    investigate,
    personal_scope,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


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
    session.add(workspace)
    session.flush()

    admin = User(email="admin@acme.test", name="Admin")
    member = User(email="member@acme.test", name="Member")
    session.add_all([admin, member])
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=admin.id, role=Role.ORG_ADMIN))
    session.add(Membership(workspace_id=workspace.id, user_id=member.id, role=Role.EMPLOYEE))

    workspace_class = WorkspaceClass(workspace_id=workspace.id, name="Eng", slug="eng")
    session.add(workspace_class)
    session.flush()
    group = Group(class_id=workspace_class.id, name="Platform", slug="platform")
    session.add(group)
    session.flush()
    team = Team(workspace_id=workspace.id, group_id=group.id, name="dev", slug="dev")
    session.add(team)
    session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=admin.id, role=ChannelRole.CHANNEL_ADMIN))
    session.add(TeamMembership(team_id=team.id, user_id=member.id, role=ChannelRole.CHANNEL_MEMBER))

    admin_gmail = Connection(
        workspace_id=workspace.id, user_id=admin.id, provider=Provider.GMAIL,
        org="admin@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW,
    )
    member_gmail = Connection(
        workspace_id=workspace.id, user_id=member.id, provider=Provider.GMAIL,
        org="member@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW,
    )
    session.add_all([admin_gmail, member_gmail])
    session.flush()

    # The admin's mailbox is shared with the channel; the member's is not.
    session.add(SharedConnection(
        scope_type=SharedScope.WORKSPACE, scope_id=workspace.id,
        connection_id=admin_gmail.id, added_by_user_id=admin.id,
    ))
    session.commit()

    return {
        "workspace": workspace, "team": team, "admin": admin, "member": member,
        "admin_gmail": admin_gmail, "member_gmail": member_gmail,
    }


def _signal(connection, external_id, subject, *, actor="Someone <s@x.test>", when=NOW, thread=None, labels=None):
    return Signal(
        workspace_id=connection.workspace_id, connection_id=connection.id, type=SignalType.EMAIL,
        external_id=external_id, actor=actor, occurred_at=when,
        payload={"subject": subject, "from": actor, "thread_id": thread or external_id, "label_ids": labels or ["UNREAD"]},
    )


def _item(connection, external_id, title, *, when=NOW):
    return AttentionItem(
        workspace_id=connection.workspace_id, connection_id=connection.id, type=AttentionType.IMPORTANT_EMAIL,
        origin=AttentionOrigin.DETECTED, state=AttentionState.NEW, source_provider="gmail",
        dedupe_key=f"email:{external_id}", title=title, why="starred, unread", priority=0.8, due_at=when,
    )


@pytest.fixture
def anchored(session, env):
    """An anchor item in the admin's shared mailbox, plus correlatable
    activity around it."""
    conn = env["admin_gmail"]
    anchor_sig = _signal(conn, "deploy-1", "Production deployment failed", actor="CI <ci@acme.test>", thread="t-1")
    session.add_all([
        anchor_sig,
        _signal(conn, "deploy-2", "Re: Production deployment failed", actor="Dev <dev@acme.test>", thread="t-1"),
        _signal(conn, "ci-2", "Nightly build report", actor="CI <ci@acme.test>", when=NOW - timedelta(hours=6)),
        _signal(conn, "rel-1", "Deployment checklist for release", actor="Ops <ops@acme.test>", when=NOW - timedelta(days=3)),
        _signal(conn, "near-1", "Standup notes", actor="Lead <lead@acme.test>", when=NOW - timedelta(hours=2)),
    ])
    item = _item(conn, "deploy-1", "Production deployment failed")
    session.add(item)
    session.commit()
    return item


# --- correlation actually works -------------------------------------------


def test_it_finds_the_conversation_the_sender_and_the_subject(session, env, anchored):
    result = investigate(session, item=anchored, scope=personal_scope(session, env["workspace"].id, env["admin"].id))

    relations = {e["relation"] for e in result.evidence}
    titles = {e["title"] for e in result.evidence}

    assert "same_thread" in relations
    assert "Re: Production deployment failed" in titles  # the reply
    assert "same_correspondent" in relations
    assert "Nightly build report" in titles  # same CI sender
    assert "Deployment checklist for release" in titles  # shared keyword


def test_the_anchor_is_not_evidence_about_itself(session, env, anchored):
    result = investigate(session, item=anchored, scope=personal_scope(session, env["workspace"].id, env["admin"].id))

    assert "deploy-1" not in {e["title"] for e in result.evidence}
    assert all(e["title"] != anchored.title for e in result.evidence)


def test_each_piece_of_evidence_is_a_real_row_with_provenance(session, env, anchored):
    """Nothing in `evidence` may be model output. Every entry must resolve
    back to a Signal the database actually holds."""
    result = investigate(session, item=anchored, scope=personal_scope(session, env["workspace"].id, env["admin"].id))

    assert result.evidence
    for entry in result.evidence:
        signal = session.get(Signal, uuid.UUID(entry["signal_id"]))
        assert signal is not None
        assert entry["title"] == signal.payload["subject"]
        assert entry["relation_label"]


def test_evidence_is_capped(session, env):
    """Cost control, enforced in code. Retrieval is ranked, so the cap drops
    the weakest relationships rather than truncating arbitrarily."""
    conn = env["admin_gmail"]
    for n in range(40):
        session.add(_signal(conn, f"bulk-{n}", f"Deployment note {n}", actor="Ops <ops@acme.test>",
                            when=NOW - timedelta(minutes=n)))
    item = _item(conn, "bulk-0", "Deployment note 0")
    session.add(item)
    session.commit()

    result = investigate(session, item=item, scope=personal_scope(session, env["workspace"].id, env["admin"].id))
    assert len(result.evidence) <= MAX_EVIDENCE


def test_no_evidence_means_no_llm_call_and_an_honest_answer(session, env):
    """A lonely item gets a truthful non-answer rather than an invented
    cause, and costs nothing."""
    conn = env["admin_gmail"]
    session.add(_signal(conn, "lonely-1", "Zqxj", actor="Nobody <n@x.test>"))
    item = _item(conn, "lonely-1", "Zqxj")
    session.add(item)
    session.commit()

    result = investigate(session, item=item, scope=personal_scope(session, env["workspace"].id, env["admin"].id))

    assert result.evidence == []
    assert result.llm_calls == 0
    assert result.confidence <= 0.3
    assert "no related activity" in result.why_it_matters.lower()


# --- the boundaries -------------------------------------------------------


def test_a_personal_investigation_cannot_reach_another_members_mailbox(session, env, anchored):
    """ATTACK: the member's private mail sits in the same workspace, with a
    subject that would match on every relationship. The admin is an
    ORG_ADMIN. It must not appear."""
    session.add(_signal(
        env["member_gmail"], "priv-1", "Production deployment failed - my private copy",
        actor="CI <ci@acme.test>", thread="t-1",
    ))
    session.commit()

    result = investigate(session, item=anchored, scope=personal_scope(session, env["workspace"].id, env["admin"].id))

    assert all("private copy" not in e["title"] for e in result.evidence)


def test_a_channel_investigation_cannot_reach_the_investigators_own_mailbox(session, env, anchored):
    """The subtle one. The member clicks Investigate inside a channel, so
    *they* are the caller - but the scope is the channel's, and their own
    private mail is not in it. Personal context must not ride along on the
    identity of whoever pressed the button."""
    session.add(_signal(
        env["member_gmail"], "priv-2", "Production deployment failed - personal notes",
        actor="CI <ci@acme.test>", thread="t-1",
    ))
    session.commit()

    result = investigate(session, item=anchored, scope=channel_scope(session, env["team"].id))

    assert result.evidence
    assert all("personal notes" not in e["title"] for e in result.evidence)


def test_an_item_outside_the_scope_is_refused_outright(session, env):
    """Fail-closed at the entrance: you cannot investigate what you cannot
    see, and the refusal happens before any retrieval."""
    session.add(_signal(env["member_gmail"], "priv-3", "Member private thing"))
    item = _item(env["member_gmail"], "priv-3", "Member private thing")
    session.add(item)
    session.commit()

    with pytest.raises(NotAuthorized):
        investigate(session, item=item, scope=personal_scope(session, env["workspace"].id, env["admin"].id))


def test_a_channel_cannot_investigate_an_unshared_item(session, env):
    session.add(_signal(env["member_gmail"], "priv-4", "Not shared with the channel"))
    item = _item(env["member_gmail"], "priv-4", "Not shared with the channel")
    session.add(item)
    session.commit()

    with pytest.raises(NotAuthorized):
        investigate(session, item=item, scope=channel_scope(session, env["team"].id))


def test_a_manual_reminder_has_nothing_to_investigate(session, env):
    """A user's own note has no external source. Saying so beats running a
    correlation over a sentence they typed."""
    item = AttentionItem(
        workspace_id=env["workspace"].id, created_by_user_id=env["admin"].id, connection_id=None,
        type=AttentionType.MANUAL, origin=AttentionOrigin.MANUAL, state=AttentionState.NEW,
        dedupe_key="manual:1", title="Call the vendor", why="you asked", priority=0.5,
    )
    session.add(item)
    session.commit()

    with pytest.raises(NotAuthorized, match="manual reminder"):
        investigate(session, item=item, scope=personal_scope(session, env["workspace"].id, env["admin"].id))


def test_excluding_the_connection_ends_channel_investigations_of_it(session, env, anchored):
    """Deny beats allow, all the way into this feature - no separate
    enforcement, because the scope comes from the same resolver."""
    from app.models.shared_connection import ChannelConnectionExclusion

    session.add(ChannelConnectionExclusion(
        team_id=env["team"].id, connection_id=env["admin_gmail"].id, excluded_by_user_id=env["admin"].id,
    ))
    session.commit()

    with pytest.raises(NotAuthorized):
        investigate(session, item=anchored, scope=channel_scope(session, env["team"].id))


# --- caching --------------------------------------------------------------


def test_the_same_item_caches_per_scope_not_per_item(session, env, anchored):
    """Two scopes, two investigations. Sharing one cache row between them
    would serve the personal scope's evidence to the channel, or vice versa -
    a cache that leaks across an authorization boundary."""
    personal = investigate(session, item=anchored, scope=personal_scope(session, env["workspace"].id, env["admin"].id))
    channel = investigate(session, item=anchored, scope=channel_scope(session, env["team"].id))

    assert personal.id != channel.id
    assert personal.scope_key.startswith("personal:")
    assert channel.scope_key.startswith("channel:")


def test_reopening_costs_nothing(session, env, anchored):
    scope = personal_scope(session, env["workspace"].id, env["admin"].id)
    first = investigate(session, item=anchored, scope=scope)
    second = investigate(session, item=anchored, scope=scope)

    assert first.id == second.id
    assert second.created_at == first.created_at  # served, not rebuilt
