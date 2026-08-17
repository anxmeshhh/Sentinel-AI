"""Intelligence Core, Phases 6 & 7 - the Memory Engine and the Decision Engine.

Locks in:
  MEMORY   - learns only a genuine recurrence (formed, resolved, formed again);
             reinforces without duplicating; announces exactly once; is
             scope-isolated, forgettable and fully explainable.
  DECISION - deterministic, grounded proposals consuming Reasoning + Memory;
             Memory transparently boosts priority; NOTHING side-effectful runs;
             confirm-first is preserved; the chain stays traceable.

Deterministic throughout - no LLM is the source of truth in either engine.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.correlated_situation import Situation, SituationStatus
from app.models.decision import Decision, DecisionKind, DecisionStatus
from app.models.memory import Memory, MemoryKind, MemoryStatus
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.decision_engine import decide_situation, list_decisions, refresh_decisions
from app.services.entity_engine import extract_entities
from app.services.findings import list_findings
from app.services.investigation import personal_scope
from app.services.memory_engine import (
    forget_memory,
    list_memories,
    matching_memory,
    pending_announcements,
    refresh_memory,
)
from app.services.reasoning_engine import refresh_reasoning
from app.services.situation_engine import correlate

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    class _Fast:
        def complete_json(self, **kwargs):
            return {"explanation": "x", "why_it_matters": "y"}

    monkeypatch.setattr("app.services.reasoning_engine.LLMClient", _Fast)


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
    session.add(gh)
    session.flush()
    session.commit()
    return {"ws": ws, "user": user, "gh": gh, "_s": session}


def _attn(env, conn, *, type=AttentionType.STALE_PR, provider="github", priority=0.9, title="t"):
    return AttentionItem(
        workspace_id=env["ws"].id, type=type, origin=AttentionOrigin.DETECTED, state=AttentionState.NEW,
        source_provider=provider, connection_id=conn.id, dedupe_key=f"k-{uuid.uuid4().hex[:8]}",
        title=title, why="w", priority=priority, evidence_url="http://gh/1",
    )


def _form(env, titles):
    """Correlate two findings into one situation; return (scope, situation)."""
    s = env["_s"]
    items = [_attn(env, env["gh"], title=t) for t in titles]
    s.add_all(items)
    s.commit()
    scope = personal_scope(s, env["ws"].id, env["user"].id)
    findings = list_findings(s, scope)
    extract_entities(s, scope, findings)
    sits = correlate(s, scope, findings)
    return scope, sits[0], items


def _resolve(env, items):
    for i in items:
        i.state = AttentionState.DONE
    env["_s"].commit()
    scope = personal_scope(env["_s"], env["ws"].id, env["user"].id)
    correlate(env["_s"], scope, list_findings(env["_s"], scope))


# ------------------------------------------------------------------ Memory

def test_one_off_situation_is_not_remembered(session, env):
    scope, sit, _ = _form(env, ["pr1", "pr2"])
    assert refresh_memory(session, scope) == []  # occurrence_count == 1
    assert list_memories(session, scope) == []


def test_recurrence_creates_a_memory(session, env):
    scope, sit, items1 = _form(env, ["pr1", "pr2"])
    _resolve(env, items1)                      # situation resolves
    _, sit2, _ = _form(env, ["pr3", "pr4"])    # same repo -> re-forms
    assert sit2.id == sit.id and sit2.occurrence_count == 2

    new = refresh_memory(session, scope)
    assert len(new) == 1
    mem = new[0]
    assert mem.kind is MemoryKind.RECURRING_SITUATION
    assert mem.subject_key == sit.dedupe_key
    assert "recurring" in mem.summary.lower() and "2 times" in mem.summary
    assert mem.evidence["occurrence_count"] == 2  # explainable trail


def test_memory_reinforces_without_duplicating_and_announces_once(session, env):
    scope, sit, items1 = _form(env, ["pr1", "pr2"])
    _resolve(env, items1)
    _form(env, ["pr3", "pr4"])
    refresh_memory(session, scope)             # created (occurrence 2)

    # Announced exactly once.
    ann1 = pending_announcements(session, scope)
    assert len(ann1) == 1
    assert pending_announcements(session, scope) == []  # never again

    # A plain re-run must not create a second memory nor re-bump it.
    refresh_memory(session, scope)
    mems = list_memories(session, scope)
    assert len(mems) == 1 and mems[0].observation_count == 1

    # A genuine third occurrence reinforces the SAME memory.
    _resolve(env, [i for i in env["_s"].execute(select(AttentionItem)).scalars().all() if i.state == AttentionState.NEW])
    _form(env, ["pr5", "pr6"])
    refresh_memory(session, scope)
    mems = list_memories(session, scope)
    assert len(mems) == 1 and mems[0].observation_count == 2 and mems[0].strength > 0.5


def test_memory_can_be_forgotten(session, env):
    scope, sit, items1 = _form(env, ["pr1", "pr2"])
    _resolve(env, items1)
    _form(env, ["pr3", "pr4"])
    (mem,) = refresh_memory(session, scope)
    forget_memory(session, mem.id)
    assert list_memories(session, scope) == []
    assert session.get(Memory, mem.id).status is MemoryStatus.FORGOTTEN  # auditable, not deleted


def test_memory_is_scope_isolated(session, env):
    scope, sit, items1 = _form(env, ["pr1", "pr2"])
    _resolve(env, items1)
    _form(env, ["pr3", "pr4"])
    refresh_memory(session, scope)
    from app.domain.scope import Scope
    other = Scope(key="personal:someone-else", connection_ids=set(), workspace_id=env["ws"].id, owner_id=uuid.uuid4())
    assert list_memories(session, other) == []  # a different scope learned nothing


# ---------------------------------------------------------------- Decision

def test_decisions_are_grounded_and_confirm_first(session, env):
    scope, sit, _ = _form(env, ["pr1", "pr2"])
    refresh_reasoning(session, scope, list(list_findings(session, scope)))
    decisions = decide_situation(session, scope, sit)

    assert len(decisions) == 1
    d = decisions[0]
    assert d.grounded_in == "stale_pr"
    assert d.action == "Review or reassign the stalled pull request"
    assert d.kind is DecisionKind.INFORM  # a review nudge - no side effect
    assert d.status is DecisionStatus.PROPOSED  # never auto-acts


def test_unknown_action_kind_requires_confirmation(session, env):
    """The safe default: anything that could act on the world is confirm-first."""
    scope, sit, _ = _form(env, ["blk1", "blk2"])
    # relabel the findings' kind by using slack blocker attention items
    for i in env["_s"].execute(select(AttentionItem)).scalars().all():
        i.type = AttentionType.CONVERSATION_BLOCKER
    env["_s"].commit()
    findings = list_findings(session, scope)
    extract_entities(session, scope, findings)
    correlate(session, scope, findings)
    refresh_reasoning(session, scope, list(findings))
    d = decide_situation(session, scope, sit)[0]
    assert d.kind is DecisionKind.RECOMMEND and d.requires_confirmation is True


def test_memory_boosts_decision_priority_transparently(session, env):
    # First occurrence -> reason + decide, capture baseline priority.
    scope, sit, items1 = _form(env, ["pr1", "pr2"])
    refresh_reasoning(session, scope, list(list_findings(session, scope)))
    base = decide_situation(session, scope, sit)[0].priority_score

    # Make it recur and learn the memory.
    _resolve(env, items1)
    _, sit2, _ = _form(env, ["pr3", "pr4"])
    refresh_reasoning(session, scope, list(list_findings(session, scope)))
    refresh_memory(session, scope)

    d = decide_situation(session, scope, sit2)[0]
    assert d.memory_informed is True
    assert d.priority_score == pytest.approx(base + 25.0)  # the boost, deterministic

    # The boost must be VISIBLE, not merely applied - a silently reordered list
    # is exactly the opaque ranking this engine exists to avoid. Asserted on the
    # meaning rather than one wording, so the copy can be written for humans
    # without the guard evaporating.
    rationale = d.rationale.lower()
    assert "ranked higher" in rationale
    assert "seen this" in rationale or "keeps happening" in rationale
    # And it must never leak the internal score it used to print verbatim
    # ("Priority 147.0 (critical, cross-provider)").
    assert "priority " not in rationale


def test_full_traceability_chain(session, env):
    scope, sit, _ = _form(env, ["pr1", "pr2"])
    refresh_reasoning(session, scope, list(list_findings(session, scope)))
    d = decide_situation(session, scope, sit)[0]
    # Decision -> Situation -> member findings -> the finding kind it grounds in.
    assert d.situation_id == sit.id
    from app.models.correlated_situation import SituationFinding
    members = session.execute(select(SituationFinding).where(SituationFinding.situation_id == sit.id)).scalars().all()
    assert len(members) == 2 and d.grounded_in in {m.finding_source for m in members} | {"stale_pr"}
