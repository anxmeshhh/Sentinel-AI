"""Intelligence Core, Phase 1 - the canonical Finding.

These lock in the two properties the consolidation promises:

1. UNIFICATION - list_findings() returns attention items and situations as one
   uniform stream, with a single tier vocabulary computed in one place.
2. BEHAVIOUR PRESERVED - the tier counts it produces are byte-identical to the
   old inline verdict logic (attention priority>=0.8; situation importance>=0.9
   and not a stalled resource). This is the guard that the refactor changed the
   model, not the numbers.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.finding import FindingSource, FindingStatus, FindingTier
from app.models.attention_item import (
    AttentionItem,
    AttentionOrigin,
    AttentionState,
    AttentionType,
)
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.situation import ProactiveSituation, ProactiveKind, ProactiveStatus
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.attention_engine import list_attention
from app.services.findings import list_findings
from app.services.investigation import personal_scope
from app.services.proactive import list_situations

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
    conn = Connection(
        workspace_id=ws.id, user_id=user.id, provider=Provider.GITHUB,
        org="acme", repo="api", encrypted_token="x", last_synced_at=NOW,
    )
    session.add(conn)
    session.flush()
    session.commit()
    return {"ws": ws, "user": user, "conn": conn}


def _attn(env, **kw):
    defaults = dict(
        workspace_id=env["ws"].id,
        type=AttentionType.STALE_PR,
        origin=AttentionOrigin.DETECTED,
        state=AttentionState.NEW,
        source_provider="github",
        connection_id=env["conn"].id,
        dedupe_key=f"k-{uuid.uuid4().hex[:8]}",
        title="t",
        why="w",
        priority=0.5,
    )
    defaults.update(kw)
    return AttentionItem(**defaults)


def _sit(env, key, kind, importance, **kw):
    defaults = dict(
        workspace_id=env["ws"].id,
        scope_key=personal_scope(env["_s"], env["ws"].id, env["user"].id).key,
        situation_key=key,
        kind=kind,
        status=ProactiveStatus.ACTIVE,
        title="s",
        evidence=[],
        evidence_count=1,
        first_seen_at=NOW,
        last_evidence_at=NOW,
        importance=importance,
        confidence=0.9,
    )
    defaults.update(kw)
    return ProactiveSituation(**defaults)


def test_unifies_both_pipelines_with_one_tier_vocabulary(session, env):
    env["_s"] = session
    session.add_all([
        _attn(env, priority=0.9, title="critical PR"),                      # critical
        _attn(env, priority=0.5, title="review PR"),                        # review
        _attn(env, origin=AttentionOrigin.MANUAL, type=AttentionType.MANUAL,
              connection_id=None, created_by_user_id=env["user"].id,
              title="my reminder"),                                          # reminder
        _attn(env, priority=0.95, state=AttentionState.DONE, title="done"),  # excluded (not NEW)
    ])
    session.add_all([
        _sit(env, "svc", ProactiveKind.SERVICE_JEOPARDY, 0.95,
             what_is_developing="Supabase is being torn down"),             # critical
        _sit(env, "repo", ProactiveKind.RESOURCE_STALLED, 0.95),            # review (never critical)
        _sit(env, "mtg", ProactiveKind.MEETING_UNPREPARED, 0.7),            # review
    ])
    session.commit()

    findings = list_findings(session, env["ws"].id, viewer_user_id=env["user"].id)

    # The DONE item is gone; everything else is present, once each.
    assert len(findings) == 6
    assert all(f.id.startswith(("attention:", "situation:")) for f in findings)

    by_tier = {t: [f for f in findings if f.tier is t] for t in FindingTier}
    assert len(by_tier[FindingTier.CRITICAL]) == 2   # attention 0.9 + jeopardy 0.95
    assert len(by_tier[FindingTier.REVIEW]) == 3      # attention 0.5 + stalled + meeting
    assert len(by_tier[FindingTier.REMINDER]) == 1    # the manual item

    # Provenance and the transitional escape hatch are both intact.
    assert {f.source for f in findings} == {FindingSource.ATTENTION, FindingSource.PROACTIVE}
    assert all(f.raw is not None for f in findings)

    # Narrative is preserved from the situation, never invented for attention.
    jeopardy = next(f for f in findings if f.kind == "service_jeopardy")
    assert jeopardy.narrative == "Supabase is being torn down"
    assert jeopardy.confidence == 0.9
    assert all(f.narrative is None for f in findings if f.source is FindingSource.ATTENTION)


def test_stalled_resource_is_never_critical_however_important(session, env):
    """The one rule with teeth: a stalled resource stays 'review' at any
    importance. Mirrors the original _situation_is_critical exactly."""
    env["_s"] = session
    session.add(_sit(env, "repo", ProactiveKind.RESOURCE_STALLED, 1.0))
    session.commit()
    (f,) = list_findings(session, env["ws"].id, viewer_user_id=env["user"].id)
    assert f.tier is FindingTier.REVIEW


def test_tier_counts_match_the_old_inline_verdict_logic(session, env):
    """Behaviour-preservation guard: recompute the verdict the way the route
    did before Phase 1, from the raw rows, and assert the canonical stream
    agrees. If these ever diverge, the refactor changed the numbers."""
    env["_s"] = session
    session.add_all([
        _attn(env, priority=0.9), _attn(env, priority=0.8), _attn(env, priority=0.79),
        _attn(env, origin=AttentionOrigin.MANUAL, type=AttentionType.MANUAL,
              connection_id=None, created_by_user_id=env["user"].id),
    ])
    session.add_all([
        _sit(env, "a", ProactiveKind.SERVICE_JEOPARDY, 0.9),
        _sit(env, "b", ProactiveKind.SERVICE_JEOPARDY, 0.89),
        _sit(env, "c", ProactiveKind.RESOURCE_STALLED, 1.0),
    ])
    session.commit()

    # --- old logic, verbatim, over the same scoped readers ------------------
    items = list_attention(session, env["ws"].id, viewer_user_id=env["user"].id)
    detected = [i for i in items if i.origin == AttentionOrigin.DETECTED]
    reminders = [i for i in items if i.origin == AttentionOrigin.MANUAL]
    sits = list_situations(session, personal_scope(session, env["ws"].id, env["user"].id))

    def _old_is_critical(s):
        return s.importance >= 0.9 and s.kind is not ProactiveKind.RESOURCE_STALLED

    old_critical = sum(1 for i in detected if i.priority >= 0.8) + sum(1 for s in sits if _old_is_critical(s))
    old_review = sum(1 for i in detected if i.priority < 0.8) + sum(1 for s in sits if not _old_is_critical(s))
    old_reminder = len(reminders)

    # --- new logic, over the canonical stream -------------------------------
    findings = list_findings(session, env["ws"].id, viewer_user_id=env["user"].id)
    new_critical = sum(1 for f in findings if f.tier is FindingTier.CRITICAL)
    new_review = sum(1 for f in findings if f.tier is FindingTier.REVIEW)
    new_reminder = sum(1 for f in findings if f.tier is FindingTier.REMINDER)

    assert (new_critical, new_review, new_reminder) == (old_critical, old_review, old_reminder)
    # attention: 0.9 + 0.8 critical, 0.79 review; situations: jeopardy 0.9 critical,
    # jeopardy 0.89 review, stalled 1.0 review; plus one manual reminder.
    assert (new_critical, new_review, new_reminder) == (3, 3, 1)


def test_attention_status_maps_onto_one_lifecycle(session, env):
    env["_s"] = session
    session.add(_attn(env, priority=0.5))  # NEW -> OPEN
    session.commit()
    (f,) = list_findings(session, env["ws"].id, viewer_user_id=env["user"].id)
    assert f.status is FindingStatus.OPEN
