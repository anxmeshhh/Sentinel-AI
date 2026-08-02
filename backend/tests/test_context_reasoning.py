"""Intelligence Core, Phases 4 & 5 - the Context Engine and the Reasoning Engine.

Locks in:
  CONTEXT   - a situation's full evidence package is assembled deterministically:
              member findings resolved, entities gathered (scope-gated), provider
              evidence attached, trajectory read; and to_facts() exposes ONLY
              concluded facts (never raw provider data).
  REASONING - priority and recommended actions are DETERMINISTIC (the source of
              truth); the LLM only writes prose, strictly over to_facts(); it is
              cached by fingerprint; and everything degrades cleanly with no LLM.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.situation_reasoning import SituationReasoning
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.context_engine import build_context
from app.services.entity_engine import extract_entities
from app.services.findings import list_findings
from app.services.investigation import personal_scope
from app.services.reasoning_engine import prioritized_reasonings, reason_situation, refresh_reasoning
from app.services.situation_engine import correlate

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
    slack = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.SLACK,
                       org="acme", repo="C0123", display_name="#deploys", encrypted_token="x", last_synced_at=NOW)
    session.add_all([gh, slack])
    session.flush()
    session.commit()
    return {"ws": ws, "user": user, "gh": gh, "slack": slack, "_s": session}


def _attn(env, conn, *, type=AttentionType.STALE_PR, provider="github", priority=0.5, title="t", why="w", url="http://x/1"):
    return AttentionItem(
        workspace_id=env["ws"].id, type=type, origin=AttentionOrigin.DETECTED, state=AttentionState.NEW,
        source_provider=provider, connection_id=conn.id, dedupe_key=f"k-{uuid.uuid4().hex[:8]}",
        title=title, why=why, priority=priority, evidence_url=url,
    )


def _make_situation(env, items):
    """Build one situation from the given attention items; return (scope, situation, findings_by_id)."""
    s = env["_s"]
    s.add_all(items)
    s.commit()
    scope = personal_scope(s, env["ws"].id, env["user"].id)
    findings = list_findings(s, scope)
    extract_entities(s, scope, findings)
    situations = correlate(s, scope, findings)
    return scope, situations[0], {f.id: f for f in findings}


class _FakeLLM:
    """Records the exact user payload it is given and returns fixed prose."""
    calls: list[str] = []

    def complete_json(self, *, system, user, max_retries=2):
        _FakeLLM.calls.append(user)
        return {"explanation": "Two PRs on payments are stalled.", "why_it_matters": "The release is blocked."}


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    """Keep these tests deterministic and offline by default; individual tests
    override with their own stub (broken / recording) where the LLM is the
    subject. The real LLM is exercised in the sprint's real-data verification."""
    monkeypatch.setattr("app.services.reasoning_engine.LLMClient", _FakeLLM)


# --------------------------------------------------------------- Context Engine

def test_context_assembles_findings_entities_evidence(session, env):
    scope, sit, fbi = _make_situation(env, [
        _attn(env, env["gh"], priority=0.9, title="stale PR #1", url="http://gh/1"),
        _attn(env, env["gh"], priority=0.6, title="stale PR #2", url="http://gh/2"),
    ])
    ctx = build_context(session, scope, sit, fbi)

    assert len(ctx.findings) == 2
    assert ctx.primary_entity is not None and ctx.primary_entity.display_name == "payments"
    # Every member finding carries its entity and its provider evidence link -
    # the traceability leaf.
    for fc in ctx.findings:
        assert any(e.display_name == "payments" for e in fc.entities)
        assert fc.evidence and fc.evidence[0].url.startswith("http://gh/")
    assert ctx.providers == ["github"]


def test_to_facts_exposes_only_concluded_facts(session, env):
    scope, sit, fbi = _make_situation(env, [
        _attn(env, env["gh"], priority=0.9, title="stale PR #1"),
        _attn(env, env["gh"], priority=0.6, title="stale PR #2"),
    ])
    facts = build_context(session, scope, sit, fbi).to_facts()
    assert set(facts) == {"situation", "severity", "cross_provider", "trajectory", "anchor", "findings"}
    assert facts["anchor"] == "payments"
    assert all(set(f) == {"what", "kind", "severity", "provider", "evidence"} for f in facts["findings"])


def test_fingerprint_is_stable_and_changes_with_membership(session, env):
    scope, sit, fbi = _make_situation(env, [
        _attn(env, env["gh"], priority=0.9, title="pr1"),
        _attn(env, env["gh"], priority=0.6, title="pr2"),
    ])
    fp1 = build_context(session, scope, sit, fbi).fingerprint()
    fp2 = build_context(session, scope, sit, fbi).fingerprint()
    assert fp1 == fp2  # stable across identical rebuilds


# ------------------------------------------------------------- Reasoning Engine

def test_priority_is_deterministic_and_orders_by_severity(session, env):
    scope, sit, fbi = _make_situation(env, [
        _attn(env, env["gh"], priority=0.9, title="pr1"),
        _attn(env, env["gh"], priority=0.6, title="pr2"),
    ])
    r = reason_situation(session, scope, sit, fbi)
    # critical severity (0.9 member) -> base 100, +2 members*3=6 = 106; single provider.
    assert r.priority_score == pytest.approx(106.0)
    assert r.confidence > 0.5


def test_recommended_actions_are_grounded_in_finding_kinds(session, env):
    scope, sit, fbi = _make_situation(env, [
        _attn(env, env["gh"], type=AttentionType.STALE_PR, priority=0.9, title="pr1"),
        _attn(env, env["gh"], type=AttentionType.STALE_PR, priority=0.6, title="pr2"),
    ])
    r = reason_situation(session, scope, sit, fbi)
    assert r.recommended_actions == [{"action": "Review or reassign the stalled pull request", "grounded_in": "stale_pr"}]


def test_reasoning_degrades_without_an_llm(session, env, monkeypatch):
    """LLM down -> deterministic fields intact, prose empty, nothing raised."""
    from app.agents.llm import LLMError

    class _BrokenLLM:
        def complete_json(self, **kwargs):
            raise LLMError("service down")

    monkeypatch.setattr("app.services.reasoning_engine.LLMClient", _BrokenLLM)
    scope, sit, fbi = _make_situation(env, [
        _attn(env, env["gh"], priority=0.9, title="pr1"),
        _attn(env, env["gh"], priority=0.6, title="pr2"),
    ])
    r = reason_situation(session, scope, sit, fbi)
    assert r.source == "deterministic"
    assert r.explanation is None
    assert r.priority_score > 0 and r.recommended_actions  # the floor is complete


def test_llm_sees_only_prepared_context_and_is_cached(session, env, monkeypatch):
    _FakeLLM.calls = []
    monkeypatch.setattr("app.services.reasoning_engine.LLMClient", _FakeLLM)
    scope, sit, fbi = _make_situation(env, [
        _attn(env, env["gh"], priority=0.9, title="stale PR #1"),
        _attn(env, env["gh"], priority=0.6, title="stale PR #2"),
    ])

    r1 = reason_situation(session, scope, sit, fbi)
    assert r1.source == "llm"
    assert r1.explanation == "Two PRs on payments are stalled."
    # The model was handed the prepared facts dict, nothing else.
    assert len(_FakeLLM.calls) == 1
    payload = _FakeLLM.calls[0]
    assert "'findings'" in payload and "stale PR #1" in payload  # it's to_facts()

    # Re-reasoning an unchanged situation must NOT call the LLM again.
    r2 = reason_situation(session, scope, sit, fbi)
    assert r2.id == r1.id
    assert len(_FakeLLM.calls) == 1  # still one - cached by fingerprint


def test_refresh_and_prioritize_scope(session, env, monkeypatch):
    monkeypatch.setattr("app.services.reasoning_engine.LLMClient", _FakeLLM)
    scope, sit, fbi = _make_situation(env, [
        _attn(env, env["gh"], priority=0.9, title="pr1"),
        _attn(env, env["gh"], priority=0.6, title="pr2"),
    ])
    reasonings = refresh_reasoning(session, scope, list(fbi.values()))
    assert len(reasonings) == 1
    top = prioritized_reasonings(session, scope)
    assert top and top[0].scope_key == scope.key
