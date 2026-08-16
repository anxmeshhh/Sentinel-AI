"""The Situations read API.

These endpoints exist because the Situation Engine's output - the product's most
valuable result - was only reachable narrowed to a single service. Nothing here
computes intelligence; it assembles what the engines already wrote. The tests
therefore care most about two things: that the scope boundary holds, and that
`why_connected` stays deterministic rather than drifting into LLM prose.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.situations import list_situations_for_scope, situation_detail
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.correlated_situation import Situation, SituationFinding, SituationStatus
from app.models.entity import Entity, EntityKind
from app.models.memory import Memory, MemoryKind, MemoryStatus
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind

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
    ws = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()
    user = User(email="u@x.test", name="U")
    other = User(email="other@x.test", name="Other")
    session.add_all([user, other])
    session.flush()
    session.add_all([
        Membership(workspace_id=ws.id, user_id=user.id, role=Role.ORG_ADMIN),
        Membership(workspace_id=ws.id, user_id=other.id, role=Role.EMPLOYEE),
    ])
    session.add(Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.ZOOM,
                           org="me@example.com", repo="meetings", encrypted_token="x"))
    session.flush()

    entity = Entity(workspace_id=ws.id, kind=EntityKind.REPO, key="github:acme/api",
                    display_name="api", first_seen_at=NOW, last_seen_at=NOW)
    session.add(entity)
    session.flush()

    sit = Situation(
        workspace_id=ws.id, scope_key=f"personal:{user.id}", dedupe_key="d1",
        primary_entity_id=entity.id, status=SituationStatus.OPEN, severity="critical",
        title="api: 2 related findings", member_count=2, peak_member_count=2,
        provider_count=2, cross_provider=True, first_seen_at=NOW, last_activity_at=NOW,
    )
    session.add(sit)
    session.flush()
    session.add_all([
        SituationFinding(situation_id=sit.id, finding_id="attention:a",
                         finding_source="attention", tier="critical", provider="zoom"),
        SituationFinding(situation_id=sit.id, finding_id="attention:b",
                         finding_source="attention", tier="review", provider="gmail"),
    ])
    session.commit()
    return {"ws": ws, "user": user, "other": other, "sit": sit, "entity": entity, "_s": session}


def test_the_list_returns_situations_for_the_callers_own_scope(session, env):
    rows = list_situations_for_scope(None, session, env["ws"].id, env["user"])
    assert len(rows) == 1
    assert rows[0]["severity"] == "critical"
    assert rows[0]["cross_provider"] is True
    assert rows[0]["providers"] == ["gmail", "zoom"]


def test_another_users_scope_sees_nothing(session, env):
    """The situation belongs to one person's view. Reading across that boundary
    is exactly what the scope model exists to prevent."""
    assert list_situations_for_scope(None, session, env["ws"].id, env["other"]) == []


def test_detail_is_refused_across_a_scope_boundary(session, env):
    """404 rather than 403 - a scope that cannot see it should not learn it
    exists."""
    with pytest.raises(HTTPException) as exc:
        situation_detail(env["sit"].id, session, env["ws"].id, env["other"])
    assert exc.value.status_code == 404


def test_why_connected_is_deterministic_and_names_the_shared_entity(session, env):
    """This sentence is the trust anchor: it proves the connection is a fact,
    not a guess, so it must never come from the LLM."""
    detail = situation_detail(env["sit"].id, session, env["ws"].id, env["user"])
    assert detail["why_connected"] == "All 2 concern the same repo, api."


def test_members_that_no_longer_resolve_are_marked_not_live(session, env):
    """A member whose finding has since resolved stays in the record - the UI
    dims it rather than silently dropping evidence."""
    detail = situation_detail(env["sit"].id, session, env["ws"].id, env["user"])
    assert len(detail["findings"]) == 2
    assert all(f["live"] is False for f in detail["findings"])  # no live findings in this fixture
    assert {f["provider"] for f in detail["findings"]} == {"zoom", "gmail"}


def test_memory_is_matched_on_the_situations_dedupe_key(session, env):
    """That key is what makes "this keeps happening" attach to the same
    situation across occurrences."""
    session.add(Memory(
        workspace_id=env["ws"].id, scope_key=f"personal:{env['user'].id}",
        kind=MemoryKind.RECURRING_SITUATION, subject_key="d1",
        summary="api keeps recurring - seen 2 times.", strength=0.6,
        observation_count=2, status=MemoryStatus.ACTIVE, evidence={},
        first_observed_at=NOW, last_observed_at=NOW,
    ))
    session.commit()

    detail = situation_detail(env["sit"].id, session, env["ws"].id, env["user"])
    assert detail["memory"]["observation_count"] == 2
    assert "keeps recurring" in detail["memory"]["summary"]


def test_a_forgotten_memory_is_not_attached(session, env):
    session.add(Memory(
        workspace_id=env["ws"].id, scope_key=f"personal:{env['user'].id}",
        kind=MemoryKind.RECURRING_SITUATION, subject_key="d1", summary="old",
        strength=0.6, observation_count=2, status=MemoryStatus.FORGOTTEN, evidence={},
        first_observed_at=NOW, last_observed_at=NOW, forgotten_at=NOW,
    ))
    session.commit()
    assert situation_detail(env["sit"].id, session, env["ws"].id, env["user"])["memory"] is None


def test_the_list_can_be_filtered_to_resolved(session, env):
    env["sit"].status = SituationStatus.RESOLVED
    env["sit"].resolved_at = NOW
    session.commit()

    assert list_situations_for_scope("open", session, env["ws"].id, env["user"]) == []
    assert len(list_situations_for_scope("resolved", session, env["ws"].id, env["user"])) == 1


def test_critical_situations_sort_above_review(session, env):
    entity2 = Entity(workspace_id=env["ws"].id, kind=EntityKind.SERVICE, key="service:x",
                     display_name="x", first_seen_at=NOW, last_seen_at=NOW)
    session.add(entity2)
    session.flush()
    session.add(Situation(
        workspace_id=env["ws"].id, scope_key=f"personal:{env['user'].id}", dedupe_key="d2",
        primary_entity_id=entity2.id, status=SituationStatus.OPEN, severity="review",
        title="x: 2 related findings", member_count=2, peak_member_count=2, provider_count=1,
        cross_provider=False, first_seen_at=NOW, last_activity_at=NOW + timedelta(hours=1),
    ))
    session.commit()

    rows = list_situations_for_scope(None, session, env["ws"].id, env["user"])
    # Severity beats recency, even though the review one is newer.
    assert [r["severity"] for r in rows] == ["critical", "review"]
