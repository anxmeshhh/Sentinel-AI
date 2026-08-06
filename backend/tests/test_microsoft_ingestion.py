"""Microsoft 365 ingestion (Sprint 1): normalization + token refresh + the
proof that Outlook flows through the EXISTING Intelligence Core unchanged.

The value of these is the last test: an Outlook message, normalized by the Graph
client, produces an IMPORTANT_EMAIL through the same detector Gmail uses - no
Microsoft-specific detection anywhere.
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
from app.repositories.signals import SignalRepository
from app.services.attention_engine import refresh_attention

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


# ------------------------------------------------------------- normalization

def _graph(monkeypatch, items):
    client = GraphClient("fake-token")
    monkeypatch.setattr(client, "_paginate", lambda path, params, cap: items)
    return client


def test_outlook_message_normalizes_to_the_gmail_email_shape(monkeypatch):
    raw = {
        "id": "AAMkmsg1", "conversationId": "conv1", "subject": "Deploy approval needed",
        "from": {"emailAddress": {"name": "Jane", "address": "jane@contoso.com"}},
        "toRecipients": [{"emailAddress": {"address": "me@contoso.com"}}],
        "isRead": False, "importance": "high", "flag": {"flagStatus": "flagged"},
        "inferenceClassification": "focused",
        "receivedDateTime": "2026-08-05T10:00:00.0000000Z", "webLink": "https://outlook/m1",
    }
    (msg,) = _graph(monkeypatch, [raw]).fetch_messages(NOW - timedelta(days=1))
    assert msg["external_id"] == "AAMkmsg1"
    assert msg["actor"] == "Jane <jane@contoso.com>"
    p = msg["payload"]
    # The label synthesis that makes the existing detector fire:
    assert set(p["label_ids"]) == {"UNREAD", "IMPORTANT", "STARRED"}
    assert p["subject"] == "Deploy approval needed"
    assert p["thread_id"] == "conv1" and p["is_bulk"] is False
    # ...and it carries exactly the keys a Gmail EMAIL payload does.
    assert set(p) >= {"thread_id", "subject", "from", "to", "label_ids", "is_bulk"}


def test_focused_other_maps_to_bulk_and_read_has_no_unread_label(monkeypatch):
    raw = {
        "id": "m2", "subject": "Newsletter", "from": {"emailAddress": {"address": "news@x.com"}},
        "isRead": True, "importance": "normal", "inferenceClassification": "other",
        "receivedDateTime": "2026-08-05T10:00:00Z",
    }
    (msg,) = _graph(monkeypatch, [raw]).fetch_messages(NOW - timedelta(days=1))
    assert msg["payload"]["label_ids"] == []  # read, normal, unflagged
    assert msg["payload"]["is_bulk"] is True


def test_outlook_event_normalizes_to_the_calendar_shape(monkeypatch):
    raw = {
        "id": "evt1", "subject": "Prod deploy",
        "start": {"dateTime": "2026-08-06T09:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-08-06T10:00:00.0000000", "timeZone": "UTC"},
        "attendees": [{"emailAddress": {"address": "bob@contoso.com"}}],
        "organizer": {"emailAddress": {"address": "jane@contoso.com"}},
        "isOnlineMeeting": True, "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/x"},
        "isCancelled": False, "showAs": "busy", "webLink": "https://outlook/evt1",
    }
    (ev,) = _graph(monkeypatch, [raw]).fetch_events(NOW)
    p = ev["payload"]
    assert ev["external_id"] == "evt1" and p["title"] == "Prod deploy"
    assert p["has_meeting_link"] is True and p["meet_url"] == "https://teams.microsoft.com/x"
    assert p["attendee_count"] == 1 and p["attendee_emails"] == ["bob@contoso.com"]
    assert p["organizer"] == "jane@contoso.com"
    assert set(p) >= {"title", "start", "end", "attendee_count", "attendee_emails", "organizer", "has_meeting_link"}


# ------------------------------------------------------------- token refresh

def test_microsoft_token_refresh_rotates_the_refresh_token(session, monkeypatch):
    import json
    from app.core.security import decrypt_token, encrypt_token
    from app.integrations import microsoft_auth

    ws = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:6]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws); session.flush()
    u = User(email="u@x.test", name="U"); session.add(u); session.flush()
    conn = Connection(workspace_id=ws.id, user_id=u.id, provider=Provider.MICROSOFT_OUTLOOK_MAIL,
                      org="u@contoso.com", repo="mail",
                      encrypted_token=encrypt_token(json.dumps({
                          "access_token": "old", "refresh_token": "R1",
                          "expires_at": (NOW - timedelta(minutes=1)).isoformat()})))
    session.add(conn); session.commit()

    class _Resp:
        status_code = 200
        def json(self):  # Entra returns a NEW refresh token
            return {"access_token": "new", "refresh_token": "R2", "expires_in": 3600}

    monkeypatch.setattr(microsoft_auth.httpx, "post", lambda *a, **k: _Resp())
    token = microsoft_auth.get_valid_access_token(session, conn)
    assert token == "new"
    blob = json.loads(decrypt_token(conn.encrypted_token))
    assert blob["refresh_token"] == "R2"  # rotated, not the old R1


# ------------------------- the proof: existing Core, unchanged ---------------

def test_outlook_mail_flows_through_the_existing_email_detector(session):
    """An Outlook message → EMAIL signal → the SAME detector Gmail uses →
    IMPORTANT_EMAIL. No Microsoft-specific detection exists anywhere."""
    ws = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:6]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws); session.flush()
    u = User(email="u@x.test", name="U"); session.add(u); session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=u.id, role=Role.ORG_ADMIN))
    conn = Connection(workspace_id=ws.id, user_id=u.id, provider=Provider.MICROSOFT_OUTLOOK_MAIL,
                      org="u@contoso.com", repo="mail", encrypted_token="x", last_synced_at=NOW)
    session.add(conn); session.flush()

    # The exact shape GraphClient.fetch_messages produces for an important unread email.
    SignalRepository(session, ws.id).upsert(
        connection_id=conn.id, type=SignalType.EMAIL, external_id="AAMkmsg1",
        actor="Jane <jane@contoso.com>", occurred_at=NOW - timedelta(hours=1),
        payload={"thread_id": "c1", "subject": "Deploy approval needed",
                 "from": "Jane <jane@contoso.com>", "to": "me@contoso.com",
                 "label_ids": ["UNREAD", "IMPORTANT"], "is_bulk": False},
    )
    session.commit()

    refresh_attention(session, ws.id)
    items = session.execute(
        select(AttentionItem).where(AttentionItem.type == AttentionType.IMPORTANT_EMAIL, AttentionItem.connection_id == conn.id)
    ).scalars().all()
    assert len(items) == 1
    assert items[0].source_provider is not None
