"""Intelligence built from data Sentinel already ingested.

Seven detectors over signals that were being stored and, in several cases,
never read at all - issues had been ingested since the GitHub module shipped
with no detector of any kind, and `changed_dirs` was fetched on every PR and
used for nothing.

Every one is deterministic: arithmetic over stored payloads, no LLM anywhere,
so each test asserts the exact fact rather than the shape of a narration.
Each also asserts the negative case, because a detector that fires on
everything is worse than none - precision over recall is the rule this module
is built on.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.attention_item import AttentionItem, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.services.attention_engine import (
    _detect_bus_factor,
    _detect_meeting_conflicts,
    _detect_meeting_overload,
    _detect_review_bottleneck,
    _detect_slow_merges,
    _detect_stale_documents,
    _detect_stale_issues,
    refresh_attention,
)

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
    user = User(email="dev@acme.test", name="Dev")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.EMPLOYEE))

    def _conn(provider, org, repo):
        c = Connection(
            workspace_id=ws.id, user_id=user.id, provider=provider,
            org=org, repo=repo, encrypted_token="x", last_synced_at=NOW,
        )
        session.add(c)
        session.flush()
        return c

    env = {
        "ws": ws, "user": user, "_s": session,
        "gh": _conn(Provider.GITHUB, "acme", "api"),
        "cal": _conn(Provider.GOOGLE_CALENDAR, "dev@acme.test", "primary"),
        "drive": _conn(Provider.GOOGLE_DRIVE, "dev@acme.test", "root"),
    }
    session.commit()
    return env


def _sig(env, conn, sig_type, external_id, occurred_at, payload, actor="dev"):
    s = Signal(
        workspace_id=env["ws"].id, connection_id=conn.id, type=sig_type,
        external_id=external_id, actor=actor, occurred_at=occurred_at, payload=payload,
    )
    env["_s"].add(s)
    return s


def _event(env, external_id, start, minutes, title, status="confirmed"):
    return _sig(
        env, env["cal"], SignalType.CALENDAR_EVENT, external_id, start,
        {
            "title": title, "start": start.isoformat(),
            "end": (start + timedelta(minutes=minutes)).isoformat(),
            "attendee_count": 2, "attendee_emails": ["a@x.test"], "organizer": "dev@acme.test",
            "has_meeting_link": True, "status": status, "url": f"https://cal/{external_id}",
        },
    )


def _pr(env, number, created, *, merged=None, closed=None, reviewers=None, dirs=None, author="dev"):
    return _sig(
        env, env["gh"], SignalType.PR, f"pr-{number}", created,
        {
            "number": number, "title": f"PR {number}", "state": "closed" if merged else "open",
            "author": author, "created_at": created.isoformat(),
            "merged_at": merged.isoformat() if merged else None,
            "closed_at": closed.isoformat() if closed else None,
            "requested_reviewers": reviewers or [], "changed_dirs": dirs or [],
            "url": f"https://gh/pr/{number}",
        },
        actor=author,
    )


# --- meetings -------------------------------------------------------------


def test_two_overlapping_meetings_are_one_conflict(session, env):
    start = NOW + timedelta(days=1)
    _event(env, "a", start, 60, "Design review")
    _event(env, "b", start + timedelta(minutes=30), 60, "1:1")
    session.commit()

    found = _detect_meeting_conflicts(session, env["ws"].id, NOW)
    assert len(found) == 1
    assert found[0]["type"] is AttentionType.MEETING_CONFLICT
    assert "30 minute overlap" in found[0]["why"]


def test_back_to_back_meetings_are_not_a_conflict(session, env):
    """Ending exactly when the next begins is a full day, not a clash."""
    start = NOW + timedelta(days=1)
    _event(env, "a", start, 60, "Standup")
    _event(env, "b", start + timedelta(minutes=60), 30, "Sync")
    session.commit()

    assert _detect_meeting_conflicts(session, env["ws"].id, NOW) == []


def test_a_cancelled_meeting_cannot_conflict(session, env):
    start = NOW + timedelta(days=1)
    _event(env, "a", start, 60, "Design review")
    _event(env, "b", start + timedelta(minutes=15), 60, "Cancelled thing", status="cancelled")
    session.commit()

    assert _detect_meeting_conflicts(session, env["ws"].id, NOW) == []


def test_an_all_day_event_does_not_collide_with_everything(session, env):
    """All-day events carry a date, not a time. Treating one as a 24-hour
    block would make every meeting that week a conflict."""
    day = (NOW + timedelta(days=1)).date().isoformat()
    _sig(env, env["cal"], SignalType.CALENDAR_EVENT, "allday", NOW + timedelta(days=1),
         {"title": "Company holiday", "start": day, "end": day, "status": "confirmed"})
    _event(env, "b", NOW + timedelta(days=1, hours=2), 60, "Standup")
    session.commit()

    assert _detect_meeting_conflicts(session, env["ws"].id, NOW) == []


def test_a_crowded_week_produces_one_overload_item(session, env):
    for i in range(12):
        _event(env, f"m{i}", NOW + timedelta(days=1, hours=i * 2), 120, f"Meeting {i}")
    session.commit()

    found = _detect_meeting_overload(session, env["ws"].id, NOW)
    assert len(found) == 1  # aggregated, not one per meeting
    assert found[0]["type"] is AttentionType.MEETING_OVERLOAD
    assert "12 meetings" in found[0]["why"]


def test_a_normal_week_is_not_overload(session, env):
    for i in range(3):
        _event(env, f"m{i}", NOW + timedelta(days=1, hours=i), 60, f"Meeting {i}")
    session.commit()

    assert _detect_meeting_overload(session, env["ws"].id, NOW) == []


# --- engineering ----------------------------------------------------------


def test_slow_merges_are_reported_per_repository(session, env):
    for i in range(3):
        created = NOW - timedelta(days=20)
        _pr(env, i, created, merged=created + timedelta(days=10))
    session.commit()

    found = _detect_slow_merges(session, env["ws"].id, NOW)
    assert len(found) == 1  # one per repo, not one per PR
    assert found[0]["type"] is AttentionType.PR_SLOW_MERGE
    assert "10 days to merge" in found[0]["title"]


def test_fast_merges_report_nothing(session, env):
    for i in range(3):
        created = NOW - timedelta(days=10)
        _pr(env, i, created, merged=created + timedelta(hours=6))
    session.commit()

    assert _detect_slow_merges(session, env["ws"].id, NOW) == []


def test_a_reviewer_with_a_queue_is_a_bottleneck(session, env):
    for i in range(5):
        _pr(env, i, NOW - timedelta(days=2), reviewers=["alice"])
    session.commit()

    found = _detect_review_bottleneck(session, env["ws"].id, NOW)
    assert len(found) == 1
    assert "5 pull requests waiting on alice" in found[0]["title"]


def test_merged_prs_do_not_count_towards_a_queue(session, env):
    """A queue is a fact about the present - a reviewer who cleared them is
    not a bottleneck."""
    for i in range(5):
        created = NOW - timedelta(days=2)
        _pr(env, i, created, merged=created + timedelta(hours=1), reviewers=["alice"])
    session.commit()

    assert _detect_review_bottleneck(session, env["ws"].id, NOW) == []


def test_a_directory_only_one_person_touches_is_a_bus_factor(session, env):
    for i in range(6):
        _pr(env, i, NOW - timedelta(days=3), dirs=["billing"], author="solo")
    session.commit()

    found = _detect_bus_factor(session, env["ws"].id, NOW)
    assert len(found) == 1
    assert found[0]["type"] is AttentionType.BUS_FACTOR
    assert "solo" in found[0]["title"] and "billing/" in found[0]["title"]


def test_a_shared_directory_is_not_a_bus_factor(session, env):
    for i in range(6):
        _pr(env, i, NOW - timedelta(days=3), dirs=["billing"], author="solo" if i % 2 else "other")
    session.commit()

    assert _detect_bus_factor(session, env["ws"].id, NOW) == []


def test_an_old_open_issue_is_stale(session, env):
    _sig(env, env["gh"], SignalType.ISSUE, "iss-1", NOW - timedelta(days=40),
         {"number": 1, "title": "Flaky test", "state": "open", "author": "dev",
          "created_at": (NOW - timedelta(days=40)).isoformat(), "closed_at": None,
          "url": "https://gh/i/1"})
    session.commit()

    found = _detect_stale_issues(session, env["ws"].id, NOW)
    assert len(found) == 1
    assert found[0]["type"] is AttentionType.ISSUE_STALE
    assert "Flaky test" in found[0]["title"]


def test_a_closed_issue_is_never_stale(session, env):
    _sig(env, env["gh"], SignalType.ISSUE, "iss-2", NOW - timedelta(days=40),
         {"number": 2, "title": "Done thing", "state": "closed", "author": "dev",
          "closed_at": (NOW - timedelta(days=30)).isoformat(), "url": "https://gh/i/2"})
    session.commit()

    assert _detect_stale_issues(session, env["ws"].id, NOW) == []


# --- knowledge ------------------------------------------------------------


def test_a_cold_shared_document_is_reported(session, env):
    _sig(env, env["drive"], SignalType.DRIVE_FILE, "doc-1", NOW - timedelta(days=200),
         {"name": "Runbook", "mime_type": "doc", "shared": True,
          "modified_by": "alice@acme.test", "url": "https://drive/1"})
    session.commit()

    found = _detect_stale_documents(session, env["ws"].id, NOW)
    assert len(found) == 1
    assert found[0]["type"] is AttentionType.DOC_STALE
    assert "alice@acme.test" in found[0]["why"]


def test_a_private_document_going_quiet_is_normal(session, env):
    """Only shared files matter - a private working doc going cold is not an
    operational fact about anything."""
    _sig(env, env["drive"], SignalType.DRIVE_FILE, "doc-2", NOW - timedelta(days=200),
         {"name": "Scratch", "shared": False, "modified_by": "dev", "url": "https://drive/2"})
    session.commit()

    assert _detect_stale_documents(session, env["ws"].id, NOW) == []


# --- the pipeline ---------------------------------------------------------


def test_the_new_detectors_reach_the_attention_list(session, env):
    """The whole point: these are not a side channel. refresh_attention must
    persist them like any other finding, so Situations, Reasoning, Decisions
    and the Assistant all consume them through the existing Core."""
    start = NOW + timedelta(days=1)
    _event(env, "a", start, 60, "Design review")
    _event(env, "b", start + timedelta(minutes=30), 60, "1:1")
    for i in range(5):
        _pr(env, i, NOW - timedelta(days=2), reviewers=["alice"])
    session.commit()

    refresh_attention(session, env["ws"].id)
    types = {i.type for i in session.execute(select(AttentionItem)).scalars()}

    assert AttentionType.MEETING_CONFLICT in types
    assert AttentionType.REVIEW_BOTTLENECK in types


def test_detection_is_idempotent(session, env):
    """Running twice must not double the list - the same fact upserts on its
    dedupe key, which is what lets this run on every sync."""
    start = NOW + timedelta(days=1)
    _event(env, "a", start, 60, "Design review")
    _event(env, "b", start + timedelta(minutes=30), 60, "1:1")
    session.commit()

    refresh_attention(session, env["ws"].id)
    first = session.execute(select(AttentionItem)).scalars().all()
    refresh_attention(session, env["ws"].id)
    second = session.execute(select(AttentionItem)).scalars().all()

    assert len(first) == len(second)
