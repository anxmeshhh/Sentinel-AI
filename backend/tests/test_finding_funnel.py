"""The finding funnel: the unanswered-mail detector, and entity-mention hygiene.

Both fixes came out of measuring the real pipeline (598 signals -> 2 live
findings), so both are pinned to the reason they exist rather than to a number.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.domain.scope import Scope
from app.models.attention_item import AttentionItem, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.entity import Entity, EntityKind, EntityMention, MentionRole
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.repositories.signals import SignalRepository
from app.services.attention_engine import (
    UNANSWERED_MAIL_DAYS,
    UNANSWERED_MAIL_MIN,
    refresh_attention,
)
from app.services.entity_engine import extract_entities

NOW = datetime.now(timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def env(session):
    ws = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()
    user = User(email="u@acme.test", name="U")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.ORG_ADMIN))
    mail = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.GMAIL,
                      org="u@acme.test", repo="gmail", encrypted_token="x", last_synced_at=NOW)
    session.add(mail)
    session.flush()
    session.commit()
    return {"ws": ws, "user": user, "mail": mail, "_s": session}


def _email(env, *, subject, labels, days_ago, conn=None):
    SignalRepository(env["_s"], env["ws"].id).upsert(
        connection_id=(conn or env["mail"]).id, type=SignalType.EMAIL,
        external_id=f"m-{uuid.uuid4().hex[:8]}", actor="Jane <jane@x.com>",
        occurred_at=NOW - timedelta(days=days_ago),
        payload={"subject": subject, "from": "Jane <jane@x.com>", "to": "me@x.com",
                 "label_ids": list(labels), "is_bulk": False, "thread_id": "t"},
    )


def _unanswered(session):
    return session.execute(
        select(AttentionItem).where(AttentionItem.type == AttentionType.UNANSWERED_MAIL)
    ).scalars().all()


def test_old_important_unread_mail_becomes_one_aggregated_finding(session, env):
    """The gap this closes: the recency detector only looks back 7 days, which is
    backwards for mail that got DROPPED. Aggregated, so a backlog is one finding
    rather than one per message."""
    for i in range(5):
        _email(env, subject=f"Contract {i}", labels=("UNREAD", "IMPORTANT"),
               days_ago=UNANSWERED_MAIL_DAYS + 10 + i)
    session.commit()
    refresh_attention(session, env["ws"].id)

    items = _unanswered(session)
    assert len(items) == 1                        # ONE finding, not five
    assert "5 important messages" in items[0].title
    assert f"over {UNANSWERED_MAIL_DAYS} days" in items[0].why
    assert items[0].priority < 0.8                # a backlog, never critical


def test_a_small_number_of_stale_messages_is_not_a_finding(session, env):
    """Below the threshold this is an untidy inbox, not an operational problem."""
    for i in range(UNANSWERED_MAIL_MIN - 1):
        _email(env, subject=f"Note {i}", labels=("UNREAD", "IMPORTANT"), days_ago=UNANSWERED_MAIL_DAYS + 5)
    session.commit()
    refresh_attention(session, env["ws"].id)
    assert _unanswered(session) == []


def test_recent_read_and_promotional_mail_are_all_excluded(session, env):
    """Precision: only genuinely old, genuinely unread, genuinely important mail."""
    for i in range(6):
        _email(env, subject=f"Recent {i}", labels=("UNREAD", "IMPORTANT"), days_ago=2)
        _email(env, subject=f"Read {i}", labels=("IMPORTANT",), days_ago=40)
        _email(env, subject=f"Promo {i}",
               labels=("UNREAD", "IMPORTANT", "CATEGORY_PROMOTIONS"), days_ago=40)
    session.commit()
    refresh_attention(session, env["ws"].id)
    assert _unanswered(session) == []


def test_starred_promotional_mail_still_counts(session, env):
    """Starring is an explicit human judgment and outranks our heuristics - the
    same rule the recency detector already follows."""
    for i in range(UNANSWERED_MAIL_MIN):
        _email(env, subject=f"Starred {i}",
               labels=("UNREAD", "STARRED", "CATEGORY_PROMOTIONS"), days_ago=UNANSWERED_MAIL_DAYS + 5)
    session.commit()
    refresh_attention(session, env["ws"].id)
    assert len(_unanswered(session)) == 1


def test_each_mailbox_gets_its_own_finding(session, env):
    """Two mailboxes with a backlog each is two situations, not one combined -
    and the detector reads EMAIL signals, so Gmail and Outlook both fire it with
    no provider branch anywhere."""
    second = Connection(workspace_id=env["ws"].id, user_id=env["user"].id,
                        provider=Provider.MICROSOFT_OUTLOOK_MAIL, org="u@contoso.com",
                        repo="mail", encrypted_token="x", last_synced_at=NOW)
    session.add(second)
    session.flush()
    for i in range(UNANSWERED_MAIL_MIN):
        _email(env, subject=f"A{i}", labels=("UNREAD", "IMPORTANT"), days_ago=30)
        _email(env, subject=f"B{i}", labels=("UNREAD", "IMPORTANT"), days_ago=30, conn=second)
    session.commit()
    refresh_attention(session, env["ws"].id)

    items = _unanswered(session)
    assert len(items) == 2
    assert {i.source_provider for i in items} == {"gmail", "microsoft_outlook_mail"}


def test_the_finding_resolves_when_the_backlog_is_cleared(session, env):
    for i in range(4):
        _email(env, subject=f"Old {i}", labels=("UNREAD", "IMPORTANT"), days_ago=30)
    session.commit()
    refresh_attention(session, env["ws"].id)
    assert len(_unanswered(session)) == 1

    # The user reads them; re-detection must stop producing the finding.
    for sig in session.execute(select(Signal)).scalars().all():
        sig.payload = {**sig.payload, "label_ids": ["IMPORTANT"]}
    session.commit()
    refresh_attention(session, env["ws"].id)
    assert [i for i in _unanswered(session) if i.state == AttentionState.NEW] == []


# --- entity-mention hygiene -------------------------------------------------

def test_orphaned_entity_mentions_are_pruned(session, env):
    """Measured on real data: an entity showed 2 mentions while only 1 live
    finding referenced it, because a mention outlived a finding that vanished
    entirely. Correlation was never fooled - it intersects with live findings -
    but the stored state was wrong, and wrong state becomes a wrong decision."""
    scope = Scope(key=f"personal:{env['user'].id}", connection_ids={env["mail"].id},
                  workspace_id=env["ws"].id, owner_id=env["user"].id)
    ent = Entity(workspace_id=env["ws"].id, kind=EntityKind.REPO, key="github:acme/api",
                 display_name="api", first_seen_at=NOW, last_seen_at=NOW)
    session.add(ent)
    session.flush()
    session.add(EntityMention(
        workspace_id=env["ws"].id, scope_key=scope.key, entity_id=ent.id,
        finding_id="attention:vanished", finding_source="attention",
        role=MentionRole.ABOUT, confidence=1.0,
    ))
    session.commit()
    assert len(session.execute(select(EntityMention)).scalars().all()) == 1

    extract_entities(session, scope, [])
    session.commit()
    assert session.execute(select(EntityMention)).scalars().all() == []


def test_pruning_never_touches_another_scopes_mentions(session, env):
    """The prune is scoped, like everything else - one person's refresh must not
    delete another's state."""
    mine = Scope(key=f"personal:{env['user'].id}", connection_ids=set(),
                 workspace_id=env["ws"].id, owner_id=env["user"].id)
    ent = Entity(workspace_id=env["ws"].id, kind=EntityKind.REPO, key="github:acme/api",
                 display_name="api", first_seen_at=NOW, last_seen_at=NOW)
    session.add(ent)
    session.flush()
    session.add(EntityMention(
        workspace_id=env["ws"].id, scope_key="personal:someone-else", entity_id=ent.id,
        finding_id="attention:theirs", finding_source="attention",
        role=MentionRole.ABOUT, confidence=1.0,
    ))
    session.commit()

    extract_entities(session, mine, [])
    session.commit()
    remaining = session.execute(select(EntityMention)).scalars().all()
    assert len(remaining) == 1 and remaining[0].scope_key == "personal:someone-else"
