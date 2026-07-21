"""The stale-external-resource bug class, found via a real failure: an email
deleted from Gmail after Sentinel's last sync crashed the body fetch as an
unhandled 500, which the browser reported as a CORS error (unhandled
exceptions bypass CORSMiddleware, so the 500 carried no
Access-Control-Allow-Origin header and the real cause was invisible).

Three layers under test: the Gmail/Drive clients' 404 handling, the
orchestrator loop's per-tool crash guard, and the app-level middleware that
guarantees even a genuinely unhandled error returns JSON with CORS headers.
"""

import uuid

import httpx
import pytest
import respx

from app.integrations.gmail_client import GmailClient, MessageGoneError
from app.integrations.google_drive_client import GoogleDriveClient


@respx.mock
def test_gmail_deleted_message_raises_message_gone():
    respx.get("https://gmail.googleapis.com/gmail/v1/users/me/messages/gone123").mock(
        return_value=httpx.Response(404, json={"error": {"code": 404}})
    )
    with GmailClient("fake-token") as client:
        with pytest.raises(MessageGoneError):
            client.fetch_message_body("gone123")


@respx.mock
def test_gmail_other_errors_still_raise_normally():
    """Only 404 means "gone" - a 403 (revoked scope etc.) must not be
    silently reclassified as a deleted message."""
    respx.get("https://gmail.googleapis.com/gmail/v1/users/me/messages/forbidden1").mock(
        return_value=httpx.Response(403, json={"error": {"code": 403}})
    )
    with GmailClient("fake-token") as client:
        with pytest.raises(httpx.HTTPStatusError):
            client.fetch_message_body("forbidden1")


@respx.mock
def test_drive_deleted_file_returns_reason_not_crash():
    respx.get("https://www.googleapis.com/drive/v3/files/gonefile").mock(
        return_value=httpx.Response(404, json={"error": {"code": 404}})
    )
    with GoogleDriveClient("fake-token") as client:
        content, reason = client.fetch_file_content("gonefile")
    assert content is None
    assert "no longer exists" in reason


def test_orchestrator_tool_crash_becomes_error_result(monkeypatch):
    """A tool blowing up mid-loop must surface as an error tool-result the
    model can react to, never a crash of the whole stream. Proven without
    an LLM: the loop's guard wraps _execute_read_tool directly."""
    from app.services import orchestrator

    class FakeToolCall:
        class function:  # noqa: N801 - mirrors the SDK object shape
            name = "search_drive"
            arguments = "{}"

        id = "call_1"

    class FakeMessage:
        content = None
        tool_calls = [FakeToolCall]

    class FakeLLM:
        def complete_with_tools(self, **kwargs):
            # First call: emit the tool call. Second call: finish.
            if not getattr(self, "_called", False):
                self._called = True
                return FakeMessage
            final = type("M", (), {"content": "done after tool failure", "tool_calls": None})
            return final

    monkeypatch.setattr(orchestrator, "LLMClient", lambda: FakeLLM())
    monkeypatch.setattr(
        orchestrator, "_execute_read_tool",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("provider exploded")),
    )

    events = list(orchestrator.run_command_stream(None, uuid.uuid4(), "find my files"))
    result = events[-1]
    assert result["status"] == "done"
    assert result["reply"] == "done after tool failure"
    assert result["steps"] == [{"tool": "search_drive", "arguments": {}}]


def test_unhandled_route_error_returns_json_500_with_cors_headers(monkeypatch):
    """The systemic property that was broken: an unhandled exception must
    come back as JSON with Access-Control-Allow-Origin intact, not as a
    header-less 500 the browser mislabels as a CORS failure. Tested against
    the real app's real middleware stack."""
    from fastapi.testclient import TestClient

    from app import main as app_main
    from app.api import deps
    from app.api.routes import mail as mail_routes

    from app.models.user import User

    app_main.app.dependency_overrides[deps.get_db] = lambda: None
    app_main.app.dependency_overrides[deps.get_workspace_id] = lambda: uuid.uuid4()
    app_main.app.dependency_overrides[deps.get_current_user] = lambda: User(id=uuid.uuid4(), email="t@t.test", name="T")
    monkeypatch.setattr(mail_routes, "list_mail", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        client = TestClient(app_main.app)
        resp = client.get("/mail", headers={"Origin": "http://localhost:5173"})
        assert resp.status_code == 500
        assert resp.json()["detail"].startswith("Something went wrong")
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
    finally:
        app_main.app.dependency_overrides.clear()


def test_drive_analytics_signature_accepts_user_id():
    """Regression: get_drive_analytics's body used user_id while its
    signature omitted it, so every /drive/analytics call 500'd on a
    NameError from the Phase A migration onward. Pin the arity so the route
    (which passes user.id) and the service can't drift again."""
    import inspect

    from app.services.drive_query import get_drive_analytics

    params = list(inspect.signature(get_drive_analytics).parameters)
    assert params == ["session", "workspace_id", "user_id"]
