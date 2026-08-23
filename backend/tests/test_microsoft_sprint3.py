"""Microsoft Sprint 3 - OneDrive, OneNote and To Do.

The claims worth pinning down:
  * The three services ride the SAME grant and the same provisioning path.
  * Graph payloads normalize into generic signals (DRIVE_FILE / NOTE / TASK),
    with no Microsoft-specific vocabulary leaking downstream.
  * The task detectors are provider-agnostic - they read TASK signals, so
    Planner or Jira would fire them unchanged - deterministic, and correct
    about the one thing that matters: the due date.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.integrations.graph_client import GraphClient
from app.models.attention_item import AttentionItem, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.providers.registry import spec_for
from app.providers.workspace_grants import MICROSOFT_GRANT
from app.repositories.signals import SignalRepository
from app.services.attention_engine import refresh_attention
from app.services.grants import provision_grant
from app.services.ingestion import _INGEST_HANDLERS

NOW = datetime.now(timezone.utc)
# The latest moment still on today's UTC date. Used wherever a test needs a
# timestamp that is both in the future and "today", which an offset from NOW
# cannot guarantee near midnight.
LATER_TODAY = NOW.replace(hour=23, minute=59, second=0, microsecond=0)


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


def _graph(monkeypatch, items):
    client = GraphClient("fake-token")
    monkeypatch.setattr(client, "_paginate", lambda path, params, cap: items)
    return client


# ------------------------------------------------- grant + provider wiring

def test_all_three_services_ride_the_same_grant(session, env):
    provision_grant(session, workspace_id=env["ws"].id, user_id=env["user"].id, grant=MICROSOFT_GRANT,
                    account_identity="u@contoso.com", encrypted_token="tok")
    rows = {c.provider: c for c in session.execute(select(Connection)).scalars().all()}
    for provider, label in ((Provider.MICROSOFT_ONEDRIVE, "onedrive"),
                            (Provider.MICROSOFT_ONENOTE, "onenote"),
                            (Provider.MICROSOFT_TODO, "todo")):
        assert provider in rows, provider
        assert rows[provider].repo == label
        assert rows[provider].encrypted_token == "tok"  # one grant, one token
        assert provider in _INGEST_HANDLERS             # and it can actually sync


def test_signal_types_are_generic_not_microsoft_specific():
    """A OneNote page is a NOTE and a To Do item is a TASK - names a future
    Notion or Jira provider can reuse without contortion."""
    assert spec_for(Provider.MICROSOFT_ONENOTE).signal_types == (SignalType.NOTE,)
    assert spec_for(Provider.MICROSOFT_TODO).signal_types == (SignalType.TASK,)
    # OneDrive reuses the existing document signal rather than inventing one.
    assert spec_for(Provider.MICROSOFT_ONEDRIVE).signal_types == (SignalType.DRIVE_FILE,)


def test_onedrive_is_resource_scoped_like_google_drive():
    """One grant reaches every file, so sharing must be fail-closed."""
    assert spec_for(Provider.MICROSOFT_ONEDRIVE).resource_scoped is True
    assert spec_for(Provider.MICROSOFT_TODO).resource_scoped is False  # personal, bounded


# --------------------------------------------------------- normalization

def test_onedrive_normalizes_and_skips_folders_and_deletions(monkeypatch):
    raw = [
        {"id": "f1", "name": "Runbook.docx", "lastModifiedDateTime": "2026-08-07T10:00:00Z",
         "lastModifiedBy": {"user": {"displayName": "Priya"}}, "file": {"mimeType": "application/msword"},
         "size": 1024, "shared": {"scope": "users"}, "webUrl": "https://od/f1"},
        {"id": "d1", "name": "Docs", "lastModifiedDateTime": "2026-08-07T10:00:00Z", "folder": {"childCount": 3}},
        {"id": "x1", "name": "Gone.txt", "lastModifiedDateTime": "2026-08-07T10:00:00Z", "deleted": {"state": "deleted"}},
        {"id": "old", "name": "Ancient.txt", "lastModifiedDateTime": "2020-01-01T10:00:00Z", "file": {}},
    ]
    files = _graph(monkeypatch, raw).recent_files(datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert [f["id"] for f in files] == ["f1"]  # folder, tombstone and pre-window all dropped
    assert files[0]["shared"] is True and files[0]["modified_by"] == "Priya"


def test_onenote_normalizes_pages(monkeypatch):
    raw = [{"id": "p1", "title": "Deploy notes", "lastModifiedDateTime": "2026-08-07T09:00:00Z",
            "parentNotebook": {"displayName": "Work"}, "parentSection": {"displayName": "Ops"},
            "links": {"oneNoteWebUrl": {"href": "https://on/p1"}}}]
    pages = _graph(monkeypatch, raw).recent_notes(datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert len(pages) == 1
    assert pages[0]["title"] == "Deploy notes" and pages[0]["notebook"] == "Work"
    assert pages[0]["url"] == "https://on/p1"


def test_todo_normalizes_tasks_across_lists(monkeypatch):
    client = GraphClient("fake-token")
    def fake_paginate(path, params, cap):
        if path == "/me/todo/lists":
            return [{"id": "L1", "displayName": "Work"}]
        return [
            {"id": "t1", "title": "Ship release", "status": "notStarted", "importance": "high",
             "dueDateTime": {"dateTime": "2026-08-06T17:00:00.0000000", "timeZone": "UTC"}},
            {"id": "t2", "title": "Done thing", "status": "completed",
             "completedDateTime": {"dateTime": "2026-08-05T10:00:00.0000000"}},
        ]
    monkeypatch.setattr(client, "_paginate", fake_paginate)
    tasks = client.tasks()
    assert {t["id"] for t in tasks} == {"t1", "t2"}
    t1 = next(t for t in tasks if t["id"] == "t1")
    assert t1["list"] == "Work" and t1["importance"] == "high" and t1["due_at"] is not None
    assert next(t for t in tasks if t["id"] == "t2")["completed_at"] is not None


# ------------------------------------------------------- task detectors

def _task(env, conn, *, task_id, title, due, completed=False, importance="normal", list_name="Tasks"):
    SignalRepository(env["_s"], env["ws"].id).upsert(
        connection_id=conn.id, type=SignalType.TASK, external_id=task_id, actor="",
        occurred_at=due or NOW,
        payload={"title": title, "list": list_name, "status": "completed" if completed else "notStarted",
                 "importance": importance, "completed": completed,
                 "due_at": due.isoformat() if due else None, "completed_at": None},
    )


def _todo_conn(env):
    c = Connection(workspace_id=env["ws"].id, user_id=env["user"].id, provider=Provider.MICROSOFT_TODO,
                   org="u@contoso.com", repo="todo", encrypted_token="x", last_synced_at=NOW)
    env["_s"].add(c)
    env["_s"].flush()
    return c


def test_overdue_and_due_today_are_detected_completed_are_not(session, env):
    conn = _todo_conn(env)
    _task(env, conn, task_id="t-over", title="Ship release", due=NOW - timedelta(days=3))
    # Anchored to the end of the UTC day, not a fixed offset from now. The
    # detector requires due >= now AND due.date() == now.date(), so
    # "NOW + 3 hours" stopped being "today" whenever the suite ran within
    # three hours of UTC midnight - the test failed every evening and passed
    # every morning, on unchanged code.
    _task(env, conn, task_id="t-today", title="Review PR", due=LATER_TODAY)
    _task(env, conn, task_id="t-future", title="Plan Q4", due=NOW + timedelta(days=10))
    _task(env, conn, task_id="t-done", title="Already done", due=NOW - timedelta(days=5), completed=True)
    _task(env, conn, task_id="t-none", title="No due date", due=None)
    session.commit()

    refresh_attention(session, env["ws"].id)
    items = session.execute(select(AttentionItem)).scalars().all()
    by_type = {i.type: i for i in items}

    assert AttentionType.TASK_OVERDUE in by_type
    assert "Ship release" in by_type[AttentionType.TASK_OVERDUE].title
    assert AttentionType.TASK_DUE_TODAY in by_type
    assert "Review PR" in by_type[AttentionType.TASK_DUE_TODAY].title
    # A completed task, a future task and an undated one are never findings.
    titles = " ".join(i.title for i in items)
    assert "Already done" not in titles and "Plan Q4" not in titles and "No due date" not in titles


def test_high_importance_overdue_outranks_a_normal_one(session, env):
    conn = _todo_conn(env)
    _task(env, conn, task_id="t-hi", title="Critical fix", due=NOW - timedelta(days=1), importance="high")
    _task(env, conn, task_id="t-lo", title="Tidy docs", due=NOW - timedelta(days=1))
    session.commit()
    refresh_attention(session, env["ws"].id)

    items = {i.title: i for i in session.execute(select(AttentionItem)).scalars().all()}
    assert items["Overdue: Critical fix"].priority > items["Overdue: Tidy docs"].priority
    assert "high importance" in items["Overdue: Critical fix"].why


def test_completing_a_task_resolves_its_finding(session, env):
    """Upsert on the task id means a completion updates the same signal, and the
    detector then stops producing it - so the finding auto-resolves."""
    conn = _todo_conn(env)
    _task(env, conn, task_id="t1", title="Ship release", due=NOW - timedelta(days=2))
    session.commit()
    refresh_attention(session, env["ws"].id)
    assert session.execute(select(AttentionItem).where(AttentionItem.type == AttentionType.TASK_OVERDUE)).scalars().all()

    _task(env, conn, task_id="t1", title="Ship release", due=NOW - timedelta(days=2), completed=True)
    session.commit()
    refresh_attention(session, env["ws"].id)
    from app.models.attention_item import AttentionState

    remaining = session.execute(
        select(AttentionItem).where(AttentionItem.type == AttentionType.TASK_OVERDUE,
                                    AttentionItem.state == AttentionState.NEW)
    ).scalars().all()
    assert remaining == []
    # And exactly one TASK signal exists - upsert updated, never duplicated.
    assert len(session.execute(select(Signal).where(Signal.type == SignalType.TASK)).scalars().all()) == 1


def test_paused_task_connection_produces_no_findings(session, env):
    conn = _todo_conn(env)
    conn.paused_at = NOW
    _task(env, conn, task_id="t1", title="Ship release", due=NOW - timedelta(days=2))
    session.commit()
    refresh_attention(session, env["ws"].id)
    assert session.execute(select(AttentionItem)).scalars().all() == []


def test_task_detectors_are_provider_agnostic(session, env):
    """The detectors read TASK signals, not a Microsoft provider - so a future
    Planner or Jira connection fires them with no new detection code."""
    import inspect

    from app.services import attention_engine as ae

    src = inspect.getsource(ae._detect_overdue_tasks) + inspect.getsource(ae._open_task_signals)
    assert "MICROSOFT" not in src.upper()
    assert "SignalType.TASK" in src
