"""Repository classification, and the one detector it justifies.

The rule this encodes, stated by the product owner: "repository silence alone
is not a finding unless there is context that makes it meaningful." The
context is the classification. A CRITICAL repository going quiet is a real
operational risk; the same silence on a normal, low, archived or experimental
repo is noise, and must not fire.

So most of these tests are about what does NOT happen - the detector staying
silent for every classification except the one a human deliberately raised.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.core.security import encrypt_token
from app.models.base import Base
from app.models.connection import Connection, Provider, ResourcePriority
from app.models.signal import Signal, SignalType
from app.models.situation import ProactiveKind, ProactiveStatus
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.investigation import personal_scope
from app.services.proactive import RESOURCE_SILENCE_THRESHOLD, _detect_stalled_critical_resources, refresh_situations

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
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(workspace)
    session.flush()
    user = User(email="dev@acme.test", name="Dev")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=workspace.id, user_id=user.id, role=Role.ORG_ADMIN))
    session.commit()
    return {"workspace": workspace, "user": user}


def _repo(session, env, *, repo="api", priority=ResourcePriority.NORMAL, paused=False):
    c = Connection(
        workspace_id=env["workspace"].id, user_id=env["user"].id, provider=Provider.GITHUB,
        org="acme", repo=repo, github_login="acme", encrypted_token=encrypt_token("t"),
        priority=priority, paused_at=NOW if paused else None,
        last_synced_at=NOW, last_success_at=NOW,
    )
    session.add(c)
    session.commit()
    return c


def _commit(session, env, connection, *, days_ago):
    sig = Signal(
        workspace_id=env["workspace"].id, connection_id=connection.id, type=SignalType.COMMIT,
        external_id=f"c{uuid.uuid4().hex[:8]}", actor="dev",
        occurred_at=NOW - timedelta(days=days_ago), payload={"message": "work"},
    )
    session.add(sig)
    session.commit()
    return sig


def _scope(session, env):
    return personal_scope(session, env["workspace"].id, env["user"].id)


def _detect(session, env):
    scope = _scope(session, env)
    from app.services.proactive import _authorized_signals

    return _detect_stalled_critical_resources(session, scope, _authorized_signals(session, scope))


# --- the finding fires only with context ----------------------------------


def test_a_silent_critical_repo_is_a_situation(session, env):
    """The one case that should fire: a repo a human marked CRITICAL, with
    real prior activity, gone quiet past the threshold."""
    repo = _repo(session, env, priority=ResourcePriority.CRITICAL)
    _commit(session, env, repo, days_ago=RESOURCE_SILENCE_THRESHOLD.days + 5)

    [candidate] = _detect(session, env)

    assert candidate.kind == ProactiveKind.RESOURCE_STALLED
    assert "acme/api" in candidate.title
    assert candidate.evidence  # the last commit, as evidence


@pytest.mark.parametrize(
    "priority",
    [ResourcePriority.NORMAL, ResourcePriority.LOW, ResourcePriority.ARCHIVED, ResourcePriority.EXPERIMENTAL],
)
def test_silence_is_not_a_finding_without_critical_context(session, env, priority):
    """The rule, tested at every level except critical. Same silence, same
    history - no finding, because nobody said this repo mattered that much."""
    repo = _repo(session, env, priority=priority)
    _commit(session, env, repo, days_ago=RESOURCE_SILENCE_THRESHOLD.days + 30)

    assert _detect(session, env) == []


def test_a_recently_active_critical_repo_is_fine(session, env):
    """Critical, but still moving - not a finding. Resuming commits is exactly
    how a stalled situation is meant to clear."""
    repo = _repo(session, env, priority=ResourcePriority.CRITICAL)
    _commit(session, env, repo, days_ago=1)

    assert _detect(session, env) == []


def test_a_critical_repo_with_no_history_is_not_stalled(session, env):
    """"Went quiet" needs a baseline. A critical repo that never produced a
    commit is new or empty, not stalled - flagging it would be a guess."""
    _repo(session, env, priority=ResourcePriority.CRITICAL)  # no commits

    assert _detect(session, env) == []


def test_a_paused_critical_repo_does_not_fire(session, env):
    """Pausing is a deliberate silence. It must not then be surfaced as an
    unexpected one."""
    repo = _repo(session, env, priority=ResourcePriority.CRITICAL, paused=True)
    _commit(session, env, repo, days_ago=RESOURCE_SILENCE_THRESHOLD.days + 10)

    assert _detect(session, env) == []


def test_activity_of_any_kind_is_a_baseline_not_only_commits(session, env):
    """The detector reads a resource's last *sign of life*, not commits
    specifically. A critical repo whose most recent activity was an issue - and
    which then went quiet - is stalled just the same. This is what makes the
    detector provider-agnostic: it never asks what the signal was, only when the
    resource last did anything. It would have failed under a commit-only filter.
    """
    repo = _repo(session, env, priority=ResourcePriority.CRITICAL)
    sig = Signal(
        workspace_id=env["workspace"].id, connection_id=repo.id, type=SignalType.ISSUE,
        external_id=f"i{uuid.uuid4().hex[:8]}", actor="dev",
        occurred_at=NOW - timedelta(days=RESOURCE_SILENCE_THRESHOLD.days + 6), payload={"title": "bug"},
    )
    session.add(sig)
    session.commit()

    [candidate] = _detect(session, env)

    assert candidate.kind == ProactiveKind.RESOURCE_STALLED
    assert "acme/api" in candidate.title


def test_longer_silence_is_more_important(session, env):
    a = _repo(session, env, repo="a", priority=ResourcePriority.CRITICAL)
    b = _repo(session, env, repo="b", priority=ResourcePriority.CRITICAL)
    _commit(session, env, a, days_ago=RESOURCE_SILENCE_THRESHOLD.days + 2)
    _commit(session, env, b, days_ago=RESOURCE_SILENCE_THRESHOLD.days + 40)

    found = {c.title: c.importance for c in _detect(session, env)}
    a_imp = next(v for k, v in found.items() if "/a" in k)
    b_imp = next(v for k, v in found.items() if "/b" in k)
    assert b_imp > a_imp


# --- it composes into the real situation pipeline --------------------------


def test_it_surfaces_as_a_live_situation_through_refresh(session, env):
    """End to end: a stalled critical repo becomes a stored, live situation
    with all the scope and lifecycle machinery every other situation has."""
    repo = _repo(session, env, priority=ResourcePriority.CRITICAL)
    _commit(session, env, repo, days_ago=RESOURCE_SILENCE_THRESHOLD.days + 12)

    live = refresh_situations(session, env["workspace"].id, _scope(session, env))

    stalled = [s for s in live if s.kind == ProactiveKind.RESOURCE_STALLED]
    assert len(stalled) == 1
    assert stalled[0].scope_key == _scope(session, env).key  # scoped like everything else


def test_resuming_commits_resolves_the_situation(session, env):
    """The lifecycle the classification enables: a repo that comes back to
    life stops being flagged, because the detector no longer emits it and the
    reconcile pass resolves the orphan."""
    repo = _repo(session, env, priority=ResourcePriority.CRITICAL)
    old = _commit(session, env, repo, days_ago=RESOURCE_SILENCE_THRESHOLD.days + 12)
    scope = _scope(session, env)
    assert any(s.kind == ProactiveKind.RESOURCE_STALLED for s in refresh_situations(session, env["workspace"].id, scope))

    # A fresh commit lands - the repo is active again.
    _commit(session, env, repo, days_ago=0)
    live = refresh_situations(session, env["workspace"].id, scope)

    assert not any(s.kind == ProactiveKind.RESOURCE_STALLED for s in live)
    # ...and the stored row is marked resolved, not deleted.
    from sqlalchemy import select
    from app.models.situation import ProactiveSituation

    stored = session.execute(
        select(ProactiveSituation).where(ProactiveSituation.situation_key == f"resource_stalled:{repo.id}")
    ).scalars().one()
    assert stored.status == ProactiveStatus.RESOLVED


def test_lowering_priority_silences_an_existing_finding(session, env):
    """Classification is a live control: dropping a repo from CRITICAL stops
    it being surfaced, which is how a person tells Sentinel to stop worrying
    about it."""
    repo = _repo(session, env, priority=ResourcePriority.CRITICAL)
    _commit(session, env, repo, days_ago=RESOURCE_SILENCE_THRESHOLD.days + 12)
    scope = _scope(session, env)
    assert any(s.kind == ProactiveKind.RESOURCE_STALLED for s in refresh_situations(session, env["workspace"].id, scope))

    from app.services.github_connections import set_priority

    set_priority(session, repo, ResourcePriority.NORMAL)
    live = refresh_situations(session, env["workspace"].id, scope)

    assert not any(s.kind == ProactiveKind.RESOURCE_STALLED for s in live)


# --- the boundary holds ----------------------------------------------------


def test_another_persons_critical_repo_does_not_enter_my_situations(session, env, session_factory=None):
    """A stalled critical repo is scoped like every situation: it appears only
    in the scope whose connections it belongs to."""
    other = User(email="other@acme.test", name="Other")
    session.add(other)
    session.flush()
    session.add(Membership(workspace_id=env["workspace"].id, user_id=other.id, role=Role.EMPLOYEE))
    theirs = Connection(
        workspace_id=env["workspace"].id, user_id=other.id, provider=Provider.GITHUB,
        org="acme", repo="secret", github_login="other", encrypted_token=encrypt_token("t"),
        priority=ResourcePriority.CRITICAL, last_synced_at=NOW, last_success_at=NOW,
    )
    session.add(theirs)
    session.commit()
    session.add(Signal(
        workspace_id=env["workspace"].id, connection_id=theirs.id, type=SignalType.COMMIT,
        external_id="x", actor="other", occurred_at=NOW - timedelta(days=30), payload={},
    ))
    session.commit()

    # My scope sees nothing of theirs.
    assert _detect(session, env) == []
