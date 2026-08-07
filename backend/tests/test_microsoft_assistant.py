"""The Microsoft 365 operations advisor.

The valuable tests here are the deterministic ones: the advisor is only as
trustworthy as the context it is handed, so these pin down that the context is
computed correctly from Sentinel's own pipeline - including the two things most
likely to become a lie, meeting conflicts and Teams availability.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider, ResourcePriority
from app.models.signal import SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.repositories.signals import SignalRepository
from app.services.microsoft_assistant import answer_microsoft_stream, microsoft_context

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
    session.commit()
    return {"ws": ws, "user": user, "_s": session}


def _conn(env, provider, *, repo, display=None, meta=None, priority=ResourcePriority.NORMAL):
    c = Connection(
        workspace_id=env["ws"].id, user_id=env["user"].id, provider=provider,
        org="u@contoso.com" if provider is not Provider.MICROSOFT_TEAMS else "T1",
        repo=repo, display_name=display, encrypted_token="x",
        last_synced_at=NOW, last_success_at=NOW, last_sync_meta=meta, priority=priority,
    )
    env["_s"].add(c)
    env["_s"].flush()
    return c


def _email(env, conn, *, subject, sender="Jane <jane@x.com>", labels=(), bulk=False, thread="t1", days_ago=0):
    SignalRepository(env["_s"], env["ws"].id).upsert(
        connection_id=conn.id, type=SignalType.EMAIL, external_id=f"m-{uuid.uuid4().hex[:8]}",
        actor=sender, occurred_at=NOW - timedelta(days=days_ago),
        payload={"subject": subject, "from": sender, "to": "me@x.com",
                 "label_ids": list(labels), "is_bulk": bulk, "thread_id": thread},
    )


def _event(env, conn, *, title, start, minutes=60, attendees=2):
    SignalRepository(env["_s"], env["ws"].id).upsert(
        connection_id=conn.id, type=SignalType.CALENDAR_EVENT, external_id=f"e-{uuid.uuid4().hex[:8]}",
        actor="organizer@x.com", occurred_at=start,
        payload={"title": title, "start": start.isoformat(),
                 "end": (start + timedelta(minutes=minutes)).isoformat(),
                 "attendee_count": attendees, "attendee_emails": [], "organizer": "organizer@x.com",
                 "has_meeting_link": True, "status": "confirmed"},
    )


# ------------------------------------------------------------------- mail

def test_mail_is_categorized_deterministically(session, env):
    mail = _conn(env, Provider.MICROSOFT_OUTLOOK_MAIL, repo="mail")
    _email(env, mail, subject="Deploy approval", labels=("UNREAD", "IMPORTANT"))
    _email(env, mail, subject="Newsletter", labels=("UNREAD",), bulk=True, thread="t9")
    _email(env, mail, subject="Direct question", labels=("UNREAD",), thread="t8")
    _email(env, mail, subject="Old read note", labels=(), days_ago=3, thread="t7")
    session.commit()

    ctx = microsoft_context(session, env["ws"].id, env["user"].id)
    m = ctx["mail"]
    assert m["total"] == 4
    assert [i["subject"] for i in m["attention"]] == ["Deploy approval"]      # unread AND important
    assert {i["subject"] for i in m["today"]} == {"Deploy approval", "Newsletter", "Direct question"}
    # "may need a reply" = unread and not bulk. The newsletter is excluded.
    assert {i["subject"] for i in m["needs_reply"]} == {"Deploy approval", "Direct question"}


def test_busy_conversations_are_detected_by_thread(session, env):
    mail = _conn(env, Provider.MICROSOFT_OUTLOOK_MAIL, repo="mail")
    for i in range(3):
        _email(env, mail, subject="Incident thread", thread="hot", days_ago=i)
    _email(env, mail, subject="One-off", thread="cold")
    session.commit()

    ctx = microsoft_context(session, env["ws"].id, env["user"].id)
    busy = ctx["mail"]["busy_threads"]
    assert len(busy) == 1
    assert busy[0]["subject"] == "Incident thread" and busy[0]["messages"] == 3


# --------------------------------------------------------------- calendar

def test_overlapping_meetings_are_computed_not_guessed(session, env):
    cal = _conn(env, Provider.MICROSOFT_OUTLOOK_CALENDAR, repo="calendar")
    base = NOW + timedelta(hours=2)
    _event(env, cal, title="Deploy review", start=base, minutes=60)
    _event(env, cal, title="Standup", start=base + timedelta(minutes=30), minutes=30)  # overlaps
    _event(env, cal, title="Later sync", start=base + timedelta(hours=3), minutes=30)  # clear
    session.commit()

    ctx = microsoft_context(session, env["ws"].id, env["user"].id)
    conflicts = ctx["calendar"]["conflicts"]
    assert len(conflicts) == 1
    assert {conflicts[0]["a"], conflicts[0]["b"]} == {"Deploy review", "Standup"}


def test_no_conflicts_when_meetings_are_sequential(session, env):
    cal = _conn(env, Provider.MICROSOFT_OUTLOOK_CALENDAR, repo="calendar")
    base = NOW + timedelta(hours=2)
    _event(env, cal, title="First", start=base, minutes=30)
    _event(env, cal, title="Second", start=base + timedelta(minutes=30), minutes=30)  # starts exactly as first ends
    session.commit()
    assert microsoft_context(session, env["ws"].id, env["user"].id)["calendar"]["conflicts"] == []


# ------------------------------------------------------------------ teams

def test_blocked_teams_data_is_reported_as_blocked_not_quiet(session, env):
    """The honesty test: a channel Microsoft refuses to return data for must be
    distinguishable from a channel that is simply quiet."""
    _conn(env, Provider.MICROSOFT_TEAMS, repo="C1", display="Platform / deploys",
          meta={"ok": True, "messages_accessible": False, "degraded": "channel_messages_permission_missing"})
    session.commit()

    ctx = microsoft_context(session, env["ws"].id, env["user"].id)
    assert ctx["teams"]["channel_count"] == 1
    assert ctx["teams"]["data_blocked"] is True
    from app.services.microsoft_assistant import _render_context
    rendered = _render_context(ctx)
    assert "licensed Microsoft 365 work or school tenant" in rendered
    assert "NOT a quiet channel" in rendered


def test_accessible_teams_channel_is_not_flagged_blocked(session, env):
    _conn(env, Provider.MICROSOFT_TEAMS, repo="C1", display="Platform / deploys",
          meta={"ok": True, "messages_accessible": True, "messages_scanned": 12})
    session.commit()
    assert microsoft_context(session, env["ws"].id, env["user"].id)["teams"]["data_blocked"] is False


def test_bare_teams_anchor_is_not_a_monitored_channel(session, env):
    _conn(env, Provider.MICROSOFT_TEAMS, repo="")  # the grant's anchor
    session.commit()
    ctx = microsoft_context(session, env["ws"].id, env["user"].id)
    assert ctx["teams"]["connected"] is True and ctx["teams"]["channel_count"] == 0


# --------------------------------------------- intelligence + grounding

def test_only_microsoft_findings_are_included(session, env):
    """The advisor is scoped to this workspace: a GitHub finding must not leak
    into a Microsoft briefing."""
    mail = _conn(env, Provider.MICROSOFT_OUTLOOK_MAIL, repo="mail")
    gh = _conn(env, Provider.GITHUB, repo="payments")
    session.add_all([
        AttentionItem(workspace_id=env["ws"].id, type=AttentionType.IMPORTANT_EMAIL,
                      origin=AttentionOrigin.DETECTED, state=AttentionState.NEW,
                      source_provider="microsoft_outlook_mail", connection_id=mail.id,
                      dedupe_key="k1", title="Deploy approval needed", why="unread + important", priority=0.9),
        AttentionItem(workspace_id=env["ws"].id, type=AttentionType.STALE_PR,
                      origin=AttentionOrigin.DETECTED, state=AttentionState.NEW,
                      source_provider="github", connection_id=gh.id,
                      dedupe_key="k2", title="stale PR", why="awaiting review", priority=0.9),
    ])
    session.commit()

    ctx = microsoft_context(session, env["ws"].id, env["user"].id)
    titles = [f["title"] for f in ctx["findings"]]
    assert titles == ["Deploy approval needed"]
    assert ctx["critical_findings"] == 1


def test_advisor_never_calls_graph(session, env):
    """Structural guarantee, not a promise in a docstring: the assistant module
    must not import a Graph client at all."""
    import app.services.microsoft_assistant as mod

    source = open(mod.__file__, encoding="utf-8").read()
    assert "graph_client" not in source
    assert "GraphClient" not in source


def test_unconnected_workspace_answers_honestly_without_an_llm(session, env):
    """No connection, no model call - it says so plainly."""
    events = list(answer_microsoft_stream(session, env["ws"].id, env["user"].id, "what needs attention?"))
    result = events[-1]
    assert result["type"] == "result" and result["status"] == "done"
    assert "isn't connected" in result["reply"]
    assert result["sources"] == []


def test_empty_but_connected_says_nothing_synced(session, env):
    """Connected but empty must read as "nothing has been synced", never as an
    invented summary."""
    _conn(env, Provider.MICROSOFT_OUTLOOK_MAIL, repo="mail")
    _conn(env, Provider.MICROSOFT_OUTLOOK_CALENDAR, repo="calendar")
    session.commit()
    from app.services.microsoft_assistant import _render_context

    rendered = _render_context(microsoft_context(session, env["ws"].id, env["user"].id))
    assert "No messages have been ingested" in rendered
    assert "Nothing scheduled today" in rendered
    assert "no findings" in rendered.lower()


def test_stream_emits_status_then_result(session, env, monkeypatch):
    _conn(env, Provider.MICROSOFT_OUTLOOK_MAIL, repo="mail")
    session.commit()

    class _Fake:
        def complete_text(self, *, system, messages, temperature=0.3):
            return "Nothing needs your attention right now."

    monkeypatch.setattr("app.services.microsoft_assistant.LLMClient", _Fake)
    events = list(answer_microsoft_stream(session, env["ws"].id, env["user"].id, "what needs attention?"))
    assert [e["type"] for e in events] == ["status", "status", "result"]
    assert events[-1]["reply"] == "Nothing needs your attention right now."
    assert any(s["kind"] == "mail" for s in events[-1]["sources"])


def test_llm_failure_degrades_without_fabricating(session, env, monkeypatch):
    from app.agents.llm import LLMError

    _conn(env, Provider.MICROSOFT_OUTLOOK_MAIL, repo="mail")
    session.commit()

    class _Broken:
        def complete_text(self, **kwargs):
            raise LLMError("down")

    monkeypatch.setattr("app.services.microsoft_assistant.LLMClient", _Broken)
    result = list(answer_microsoft_stream(session, env["ws"].id, env["user"].id, "briefing"))[-1]
    assert result["status"] == "error"
    assert "couldn't complete that" in result["reply"]
