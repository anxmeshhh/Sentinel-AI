"""Intelligence Core, Phases 2 & 3 - the Entity Engine and the Situation Engine.

These lock in the properties the two engines promise:

  ENTITY   - findings resolve to canonical entities deterministically, from
             structured provenance (connection) and a conservative text bridge.
  SITUATION- >= 2 findings sharing a strong entity become ONE situation; it is
             cross-provider when its members span providers; it evolves rather
             than duplicating; it auto-resolves; it records its peak (trajectory);
             and it stays fully traceable back to its atomic findings.

No LLM anywhere. Everything is a deterministic function of the findings.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.correlated_situation import Situation, SituationFinding, SituationStatus
from app.models.entity import Entity, EntityKind, EntityMention, MentionRole
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.entity_engine import extract_entities
from app.services.findings import list_findings
from app.services.investigation import personal_scope
from app.services.situation_engine import correlate, list_situations, refresh_intelligence_for_workspace

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
    gh = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.GITHUB,
                    org="acme", repo="payments", encrypted_token="x", last_synced_at=NOW)
    gh2 = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.GITHUB,
                     org="acme", repo="billing", encrypted_token="x", last_synced_at=NOW)
    slack = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.SLACK,
                       org="acme", repo="C0123", display_name="#deploys", encrypted_token="x", last_synced_at=NOW)
    session.add_all([gh, gh2, slack])
    session.flush()
    session.commit()
    return {"ws": ws, "user": user, "gh": gh, "gh2": gh2, "slack": slack, "_s": session}


def _attn(env, conn, *, type=AttentionType.STALE_PR, provider="github", priority=0.5, title="t", why="w", state=AttentionState.NEW):
    return AttentionItem(
        workspace_id=env["ws"].id, type=type, origin=AttentionOrigin.DETECTED, state=state,
        source_provider=provider, connection_id=conn.id, dedupe_key=f"k-{uuid.uuid4().hex[:8]}",
        title=title, why=why, priority=priority,
    )


def _run(env):
    """extract + correlate for the one user, returning (findings, situations)."""
    s = env["_s"]
    findings = list_findings(s, env["ws"].id, viewer_user_id=env["user"].id)
    extract_entities(s, env["ws"].id, findings)
    scope = personal_scope(s, env["ws"].id, env["user"].id).key
    situations = correlate(s, env["ws"].id, scope, findings)
    return findings, situations


# ---------------------------------------------------------------- Entity Engine

def test_github_finding_resolves_to_a_repo_entity(session, env):
    session.add(_attn(env, env["gh"], title="stale PR"))
    session.commit()
    _run(env)

    repo = session.execute(select(Entity).where(Entity.kind == EntityKind.REPO)).scalar_one()
    assert repo.key == "github:acme/payments"
    assert repo.display_name == "payments"
    mention = session.execute(select(EntityMention).where(EntityMention.entity_id == repo.id)).scalar_one()
    assert mention.role is MentionRole.ABOUT


def test_slack_finding_resolves_to_a_channel_entity(session, env):
    session.add(_attn(env, env["slack"], type=AttentionType.SLACK_BLOCKER, provider="slack", title="blocked"))
    session.commit()
    _run(env)
    chan = session.execute(select(Entity).where(Entity.kind == EntityKind.CHANNEL)).scalar_one()
    assert chan.key == "slack:C0123"
    assert chan.display_name == "#deploys"


def test_extraction_is_idempotent(session, env):
    session.add(_attn(env, env["gh"]))
    session.commit()
    _run(env)
    _run(env)
    assert session.execute(select(Entity)).scalars().all().__len__() == 1
    # one ABOUT mention, not two
    assert len(session.execute(select(EntityMention)).scalars().all()) == 1


# ------------------------------------------------------------- Situation Engine

def test_two_findings_on_one_repo_form_one_situation(session, env):
    session.add_all([
        _attn(env, env["gh"], priority=0.9, title="stale PR #1"),
        _attn(env, env["gh"], priority=0.6, title="stale PR #2"),
    ])
    session.commit()
    _, situations = _run(env)

    assert len(situations) == 1
    sit = situations[0]
    assert sit.member_count == 2
    assert sit.status is SituationStatus.OPEN
    assert sit.cross_provider is False
    assert sit.severity == "critical"  # worst of 0.9 (critical) and 0.6 (review)
    # Traceable back to exactly its two findings.
    members = session.execute(select(SituationFinding).where(SituationFinding.situation_id == sit.id)).scalars().all()
    assert len(members) == 2


def test_a_single_finding_is_not_a_situation(session, env):
    session.add(_attn(env, env["gh"]))
    session.commit()
    _, situations = _run(env)
    assert situations == []


def test_cross_provider_correlation_via_text_bridge(session, env):
    """A GitHub PR on repo 'payments' and a Slack blocker whose text names
    'payments' correlate into ONE cross-provider situation - the whole point."""
    session.add_all([
        _attn(env, env["gh"], priority=0.9, title="stale PR", why="review needed"),
        _attn(env, env["slack"], type=AttentionType.SLACK_BLOCKER, provider="slack",
              priority=0.85, title="we're blocked on the payments deploy", why="waiting on approval"),
    ])
    session.commit()
    _, situations = _run(env)

    repo_sit = next(s for s in situations if s.primary_entity_id ==
                    session.execute(select(Entity).where(Entity.kind == EntityKind.REPO)).scalar_one().id)
    assert repo_sit.member_count == 2
    assert repo_sit.cross_provider is True
    assert repo_sit.provider_count == 2
    assert "across" in repo_sit.title


def test_person_alone_does_not_anchor_a_situation(session, env):
    """Two findings that share only a person (weak) must not correlate - only
    strong entities (repo/channel/service) anchor situations. Here the two
    findings are on DIFFERENT repos, so nothing strong is shared."""
    session.add_all([
        _attn(env, env["gh"], title="pr a"),
        _attn(env, env["gh2"], title="pr b"),
    ])
    session.commit()
    _, situations = _run(env)
    assert situations == []


def test_situation_evolves_and_auto_resolves_with_trajectory(session, env):
    a = _attn(env, env["gh"], priority=0.9, title="pr 1")
    b = _attn(env, env["gh"], priority=0.6, title="pr 2")
    session.add_all([a, b])
    session.commit()
    _, situations = _run(env)
    sit_id = situations[0].id
    assert situations[0].peak_member_count == 2

    # One finding resolves (DONE -> drops out of list_findings). Cluster falls to
    # one -> the situation auto-resolves, but its peak is remembered.
    b.state = AttentionState.DONE
    session.commit()
    _, situations2 = _run(env)
    assert situations2 == []  # no longer an OPEN correlated situation
    resolved = session.get(Situation, sit_id)
    assert resolved.status is SituationStatus.RESOLVED
    assert resolved.resolved_at is not None
    assert resolved.peak_member_count == 2  # trajectory preserved


def test_reforming_reuses_the_same_row_not_a_duplicate(session, env):
    session.add_all([_attn(env, env["gh"], title="pr 1"), _attn(env, env["gh"], title="pr 2")])
    session.commit()
    _run(env)
    _run(env)  # run twice
    rows = session.execute(select(Situation)).scalars().all()
    assert len(rows) == 1  # dedupe_key keeps it one row


def test_end_to_end_refresh_for_workspace(session, env):
    session.add_all([
        _attn(env, env["gh"], priority=0.9, title="stale PR"),
        _attn(env, env["slack"], type=AttentionType.SLACK_BLOCKER, provider="slack",
              priority=0.85, title="blocked on the payments deploy"),
    ])
    session.commit()
    situations = refresh_intelligence_for_workspace(session, env["ws"].id)
    assert any(s.cross_provider for s in situations)
    scope = personal_scope(session, env["ws"].id, env["user"].id).key
    assert len(list_situations(session, env["ws"].id, scope)) >= 1
