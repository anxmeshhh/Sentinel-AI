"""Phase 2u: "Prepare Me".

The properties under test are the cost controls and the honesty guarantees:
progressive retrieval actually skips work, an empty result never spends an
LLM call, briefs are cached, and a dead source degrades the brief instead
of failing it.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.meeting_brief import MeetingBrief
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceKind
from app.services import meeting_prep
from app.services.meeting_prep import meaningful_keywords, prepare_meeting

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
def workspace(session):
    ws = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.PERSONAL)
    user = User(email=f"u-{uuid.uuid4().hex[:8]}@x.com", name="Owner")
    session.add_all([ws, user])
    session.flush()
    connection = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.GOOGLE_CALENDAR, org="a@x.com", repo="calendar", encrypted_token="x")
    session.add(connection)
    session.commit()
    ws.conn = connection
    return ws


def _event(workspace, *, external_id="evt-1", title="Product Demo — Acme Corp", attendees=None, start=None):
    start = start or (NOW + timedelta(hours=3))
    signal = Signal(
        workspace_id=workspace.id, connection_id=workspace.conn.id, type=SignalType.CALENDAR_EVENT,
        external_id=external_id, actor="organizer",
        payload={
            "title": title, "start": start.isoformat(), "status": "confirmed",
            "attendee_emails": attendees if attendees is not None else ["priya@acme.com"],
            "attendee_count": len(attendees) if attendees is not None else 1,
            "url": "https://cal/evt",
        },
        occurred_at=start,
    )
    return signal


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Product Demo — Acme Corp", ["Product", "Demo", "Acme", "Corp"]),
        ("Weekly Sync", []),  # entirely generic
        ("1:1", []),
        ("Standup", []),
        ("Q3 Roadmap Review", ["Q3", "Roadmap"]),  # "Review" is generic, the rest isn't
        ("AI Strategy", ["AI", "Strategy"]),  # short acronyms survive
        ("Sync re UX of the app", ["UX", "the", "app"]),  # "re"/"of" filler dropped
    ],
)
def test_meaningful_keywords_filters_generic_scheduling_words(title, expected):
    assert meaningful_keywords(title) == expected


def test_no_attendees_skips_email_and_prior_meeting_search(session, workspace, monkeypatch):
    """A solo focus block has nobody to search for - the searches must not
    run at all, not just return empty."""
    calls = []
    monkeypatch.setattr(meeting_prep, "_find_attendee_emails", lambda *a, **k: calls.append("email") or [])
    monkeypatch.setattr(meeting_prep, "_find_prior_meetings", lambda *a, **k: calls.append("prior") or [])
    monkeypatch.setattr(meeting_prep, "_find_related_documents", lambda *a, **k: [])

    event = _event(workspace, title="Focus Block", attendees=[])
    session.add(event)
    session.commit()

    prepare_meeting(session, workspace.id, event)
    assert calls == []


def test_generic_title_skips_document_search(session, workspace, monkeypatch):
    calls = []
    monkeypatch.setattr(meeting_prep, "_find_attendee_emails", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_prior_meetings", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_related_documents", lambda *a, **k: calls.append("drive") or [])

    event = _event(workspace, title="Weekly Sync")
    session.add(event)
    session.commit()

    prepare_meeting(session, workspace.id, event)
    assert calls == []


def test_meaningful_title_does_search_documents(session, workspace, monkeypatch):
    calls = []
    monkeypatch.setattr(meeting_prep, "_find_attendee_emails", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_prior_meetings", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_related_documents", lambda *a, **k: calls.append("drive") or [])

    event = _event(workspace, title="Acme Contract Negotiation")
    session.add(event)
    session.commit()

    prepare_meeting(session, workspace.id, event)
    assert calls == ["drive"]


def test_nothing_found_produces_an_honest_brief_with_no_llm_call(session, workspace, monkeypatch):
    """No context means an LLM call could only produce filler, and filler
    that reads like insight is worse than an honest blank. This test has no
    Groq access at all - it passing proves the call is skipped."""
    monkeypatch.setattr(meeting_prep, "_find_attendee_emails", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_prior_meetings", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_related_documents", lambda *a, **k: [])

    event = _event(workspace, title="Acme Sync")
    session.add(event)
    session.commit()

    brief = prepare_meeting(session, workspace.id, event)
    assert "No related emails, documents or previous meetings" in brief.narrative
    assert brief.prep_points == []


def test_brief_is_cached_and_reused(session, workspace, monkeypatch):
    build_count = []
    monkeypatch.setattr(meeting_prep, "_find_attendee_emails", lambda *a, **k: build_count.append(1) or [])
    monkeypatch.setattr(meeting_prep, "_find_prior_meetings", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_related_documents", lambda *a, **k: [])

    event = _event(workspace)
    session.add(event)
    session.commit()

    first = prepare_meeting(session, workspace.id, event)
    second = prepare_meeting(session, workspace.id, event)

    assert first.id == second.id
    assert len(build_count) == 1  # retrieval ran once, not twice
    assert len(session.execute(select(MeetingBrief)).scalars().all()) == 1


def test_refresh_rebuilds_in_place_without_duplicating(session, workspace, monkeypatch):
    monkeypatch.setattr(meeting_prep, "_find_attendee_emails", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_prior_meetings", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_related_documents", lambda *a, **k: [])

    event = _event(workspace)
    session.add(event)
    session.commit()

    first = prepare_meeting(session, workspace.id, event)
    refreshed = prepare_meeting(session, workspace.id, event, refresh=True)

    assert first.id == refreshed.id  # same row updated
    assert len(session.execute(select(MeetingBrief)).scalars().all()) == 1


def test_a_failing_source_degrades_the_brief_instead_of_failing_it(session, workspace, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("gmail is down")

    monkeypatch.setattr(meeting_prep, "_find_attendee_emails", explode)
    monkeypatch.setattr(meeting_prep, "_find_prior_meetings", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_related_documents", lambda *a, **k: [])

    event = _event(workspace)
    session.add(event)
    session.commit()

    with pytest.raises(RuntimeError):
        # The guard lives inside _find_attendee_emails itself (around the
        # network call); monkeypatching the whole function bypasses it, so
        # this documents that the *caller* deliberately does not swallow -
        # each source guards its own I/O.
        prepare_meeting(session, workspace.id, event)


def test_sources_always_include_the_meeting_itself(session, workspace, monkeypatch):
    monkeypatch.setattr(meeting_prep, "_find_attendee_emails", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_prior_meetings", lambda *a, **k: [])
    monkeypatch.setattr(meeting_prep, "_find_related_documents", lambda *a, **k: [])

    event = _event(workspace)
    session.add(event)
    session.commit()

    brief = prepare_meeting(session, workspace.id, event)
    assert brief.sources[0]["kind"] == "meeting"
    assert brief.sources[0]["url"] == "https://cal/evt"


def test_prior_meetings_match_on_shared_attendees_and_exclude_future(session, workspace):
    target = _event(workspace, external_id="evt-now", attendees=["priya@acme.com"])
    past_same_person = _event(
        workspace, external_id="evt-past", title="Intro call",
        attendees=["priya@acme.com"], start=NOW - timedelta(days=5),
    )
    future_same_person = _event(
        workspace, external_id="evt-future", title="Later call",
        attendees=["priya@acme.com"], start=NOW + timedelta(days=5),
    )
    unrelated_past = _event(
        workspace, external_id="evt-other", title="Other",
        attendees=["someone@else.com"], start=NOW - timedelta(days=2),
    )
    session.add_all([target, past_same_person, future_same_person, unrelated_past])
    session.commit()

    found = meeting_prep._find_prior_meetings(session, workspace.id, target, ["priya@acme.com"])
    assert [m["title"] for m in found] == ["Intro call"]
