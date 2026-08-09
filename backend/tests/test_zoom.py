"""Zoom: normalization, ingestion, capability honesty, and the write actions.

The tests are weighted toward the ONE claim the whole design rests on - that a
Zoom meeting is indistinguishable from any other calendar event once it reaches
Sentinel - because if that fails, every "no Zoom-specific pipeline" statement
elsewhere becomes false.
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.integrations.zoom_client import (
    ZoomClient,
    ZoomError,
    ZoomPlanError,
    ZoomScopeError,
    _vtt_to_text,
)
from app.models.attention_item import AttentionItem, AttentionState, AttentionType
from app.models.base import Base
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.models.user import User
from app.models.workspace import Membership, Role, Workspace, WorkspaceKind
from app.providers.registry import spec_for
from app.services.action_registry import REGISTRY, Reversibility
from app.services.attention_engine import refresh_attention
from app.services.zoom_capabilities import CapabilityState, PlanType, clear_cache, describe_account

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


@pytest.fixture(autouse=True)
def _clear_capability_cache():
    clear_cache()
    yield
    clear_cache()


def _client(handler) -> ZoomClient:
    """A ZoomClient wired to a mock transport, so the normalization logic is
    tested against real response shapes without touching the network."""
    client = ZoomClient("token")
    client._client = httpx.Client(
        base_url="https://api.zoom.us/v2",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer token"},
    )
    return client


def _meeting(**over) -> dict:
    base = {
        "id": 84512345678,
        "uuid": "abc123==",
        "topic": "Weekly sync",
        "type": 2,
        "start_time": (NOW + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration": 45,
        "timezone": "Asia/Kolkata",
        "join_url": "https://zoom.us/j/84512345678",
        "host_email": "me@example.com",
    }
    base.update(over)
    return base


# --- normalization: the load-bearing claim ---------------------------------


def test_a_zoom_meeting_normalizes_to_the_shared_calendar_payload():
    """The whole architecture rests on this: once normalized, nothing downstream
    can tell a Zoom meeting from a Google or Outlook event."""
    def handler(request):
        if "previous_meetings" in str(request.url):
            return httpx.Response(200, json={"meetings": []})
        return httpx.Response(200, json={"meetings": [_meeting()]})

    with _client(handler) as client:
        out = client.fetch_meetings(NOW - timedelta(days=1))

    assert len(out) == 1
    payload = out[0]["payload"]
    # Exactly the keys graph_client.fetch_events and the Google client produce.
    for key in ("title", "start", "end", "attendee_count", "organizer", "has_meeting_link", "meet_url", "status", "url"):
        assert key in payload, f"missing shared calendar key: {key}"
    assert payload["title"] == "Weekly sync"
    assert payload["meet_url"] == "https://zoom.us/j/84512345678"
    assert payload["status"] == "confirmed"
    # end is derived from duration - Zoom's list response has no end time.
    assert payload["end"] > payload["start"]


def test_unknown_attendee_count_is_null_not_zero():
    """Zoom's meeting list carries no roster. Reporting 0 attendees would be a
    lie; None means "this provider does not say"."""
    def handler(request):
        return httpx.Response(200, json={"meetings": [_meeting()] if "upcoming" in str(request.url) else []})

    with _client(handler) as client:
        out = client.fetch_meetings(NOW - timedelta(days=1))
    assert out[0]["payload"]["attendee_count"] is None


def test_a_recurring_meeting_with_no_fixed_time_is_skipped():
    """Zoom omits start_time for those. Inventing one would put a meeting that
    is not happening in front of a user."""
    def handler(request):
        rows = [_meeting(id=1, start_time=None), _meeting(id=2)] if "upcoming" in str(request.url) else []
        return httpx.Response(200, json={"meetings": rows})

    with _client(handler) as client:
        out = client.fetch_meetings(NOW - timedelta(days=1))
    assert [m["external_id"] for m in out] == ["2"]


def test_one_failing_list_type_does_not_lose_the_other():
    """upcoming and previous are separate calls; a permission gap on one must
    not silently empty the whole sync."""
    def handler(request):
        if "previous_meetings" in str(request.url):
            return httpx.Response(500, json={"message": "boom"})
        return httpx.Response(200, json={"meetings": [_meeting()]})

    with _client(handler) as client:
        out = client.fetch_meetings(NOW - timedelta(days=1))
    assert len(out) == 1


def test_a_meeting_in_both_lists_is_ingested_once():
    """Around its start time a meeting legitimately appears in both."""
    def handler(request):
        return httpx.Response(200, json={"meetings": [_meeting()]})

    with _client(handler) as client:
        out = client.fetch_meetings(NOW - timedelta(days=1))
    assert len(out) == 1


# --- the payoff: existing detectors fire, with no Zoom code ------------------


def test_a_zoom_meeting_fires_the_existing_meeting_detector(session):
    """No Zoom detector exists. This finding is produced by the same
    _detect_upcoming_meetings that serves Google and Outlook."""
    ws = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:8]}", kind=WorkspaceKind.ORGANIZATION)
    session.add(ws)
    session.flush()
    user = User(email="u@x.test", name="U")
    session.add(user)
    session.flush()
    session.add(Membership(workspace_id=ws.id, user_id=user.id, role=Role.ORG_ADMIN))
    conn = Connection(workspace_id=ws.id, user_id=user.id, provider=Provider.ZOOM,
                      org="me@example.com", repo="meetings", encrypted_token="x", last_synced_at=NOW)
    session.add(conn)
    session.flush()

    start = NOW + timedelta(hours=2)
    session.add(Signal(
        workspace_id=ws.id, connection_id=conn.id, type=SignalType.CALENDAR_EVENT,
        external_id="84512345678", actor="me@example.com", occurred_at=start,
        payload={
            "title": "Weekly sync", "start": start.isoformat(),
            "end": (start + timedelta(minutes=45)).isoformat(),
            "attendee_count": None, "meet_url": "https://zoom.us/j/8451",
            "status": "confirmed", "url": "https://zoom.us/j/8451",
        },
    ))
    session.commit()

    refresh_attention(session, ws.id)
    items = session.execute(
        select(AttentionItem).where(AttentionItem.type == AttentionType.UPCOMING_MEETING)
    ).scalars().all()

    assert len(items) == 1
    assert items[0].title == "Weekly sync"
    # The bug this fixes: source_provider used to be hardcoded "google_calendar",
    # so a Zoom (or Outlook) meeting never reached its own workspace rail.
    assert items[0].source_provider == "zoom"
    assert "has a join link" in items[0].why


def test_zoom_declares_only_calendar_event():
    """A Zoom-specific signal type would mean a Zoom-specific detector, which is
    exactly what this design avoids."""
    assert spec_for(Provider.ZOOM).signal_types == (SignalType.CALENDAR_EVENT,)


# --- capabilities: a plan limit is a fact, not an error ----------------------


def _capability_handler(*, plan_type: int, recordings_status: int, recordings_body: dict | None = None):
    def handler(request):
        path = request.url.path
        if path.endswith("/users/me"):
            return httpx.Response(200, json={
                "id": "u1", "email": "me@example.com", "first_name": "A", "last_name": "B",
                "account_id": "acc", "type": plan_type, "timezone": "Asia/Kolkata",
                "personal_meeting_url": "https://zoom.us/j/111",
            })
        if "recordings" in path:
            return httpx.Response(recordings_status, json=recordings_body or {"meetings": []})
        return httpx.Response(404, json={})
    return handler


def test_a_free_account_reports_recordings_as_a_plan_limit(monkeypatch):
    """The Teams-license lesson applied to Zoom: say what is true about the
    account rather than showing an error."""
    import app.services.zoom_capabilities as caps

    monkeypatch.setattr(caps, "ZoomClient", lambda token: _client(
        _capability_handler(plan_type=1, recordings_status=400,
                            recordings_body={"message": "This feature is not available for your plan"})
    ))
    account = describe_account("token", account_key="k1")

    assert account.plan is PlanType.BASIC
    assert account.recordings is CapabilityState.REQUIRES_PLAN
    assert account.participants is CapabilityState.REQUIRES_PLAN
    detail = account.as_dict()["capabilities"]["recordings"]["detail"]
    assert "paid plans" in detail and "local" in detail


def test_a_licensed_account_with_no_recordings_yet_is_still_available(monkeypatch):
    """"You have no recordings" and "your plan cannot record" are completely
    different things to tell someone."""
    import app.services.zoom_capabilities as caps

    monkeypatch.setattr(caps, "ZoomClient", lambda token: _client(
        _capability_handler(plan_type=2, recordings_status=200, recordings_body={"meetings": []})
    ))
    account = describe_account("token", account_key="k2")

    assert account.plan is PlanType.LICENSED
    assert account.recordings is CapabilityState.AVAILABLE
    assert account.participants is CapabilityState.AVAILABLE


def test_a_failed_probe_reports_unknown_rather_than_guessing(monkeypatch):
    """A diagnostic must never break the page it is diagnosing, and must not
    invent a confident answer it does not have."""
    import app.services.zoom_capabilities as caps

    def explode(token):
        raise RuntimeError("network down")

    monkeypatch.setattr(caps, "ZoomClient", explode)
    account = describe_account("token", account_key="k3")

    assert account.plan is PlanType.UNKNOWN
    assert account.recordings is CapabilityState.UNKNOWN
    assert account.participants is CapabilityState.UNKNOWN


def test_a_missing_scope_is_reported_as_such_not_as_unknown(monkeypatch):
    """Found by live testing. Zoom answers 4711 "does not contain scopes", which
    is a DEFINITE answer; the probe used to report "could not tell" and throw
    that information away."""
    import app.services.zoom_capabilities as caps

    monkeypatch.setattr(caps, "ZoomClient", lambda token: _client(
        _capability_handler(
            plan_type=1, recordings_status=400,
            recordings_body={"code": 4711, "message": "Invalid access token, does not contain scopes:[cloud_recording:read:list_user_recordings]."},
        )
    ))
    account = describe_account("token", account_key="k4")
    assert account.recordings is CapabilityState.REQUIRES_SCOPE
    detail = account.as_dict()["capabilities"]["recordings"]["detail"]
    # The remedy must be named, and it differs from the plan remedy.
    assert "reconnect" in detail


def test_a_missing_scope_is_distinct_from_a_plan_limit():
    """Telling someone to buy a plan when they only needed to reconnect - or the
    reverse - is worse than saying nothing, so the two stay separate types."""
    def scope_handler(request):
        return httpx.Response(400, json={"code": 4711, "message": "does not contain scopes:[x]"})

    with _client(scope_handler) as client:
        with pytest.raises(ZoomScopeError):
            client.recordings()
    # ZoomScopeError is still a ZoomError, so existing handlers keep working.
    assert issubclass(ZoomScopeError, ZoomError)
    assert not issubclass(ZoomScopeError, ZoomPlanError)


def test_the_account_email_fills_in_a_missing_host(monkeypatch):
    """Live-observed: Zoom omits host_email from the list response for a freshly
    created meeting, leaving an opaque host_id that renders as noise. These are
    that account's own meetings, so its owner IS the host - not a guess."""
    def handler(request):
        rows = [_meeting(host_email=None, host_id="E36sTSzyTtK3waNIECaf2Q")] if "upcoming" in str(request.url) else []
        return httpx.Response(200, json={"meetings": rows})

    with _client(handler) as client:
        out = client.fetch_meetings(NOW - timedelta(days=1), account_email="me@example.com")
    assert out[0]["actor"] == "me@example.com"
    assert out[0]["payload"]["organizer"] == "me@example.com"


def test_a_real_host_email_still_wins_over_the_fallback():
    def handler(request):
        rows = [_meeting(host_email="someone.else@example.com")] if "upcoming" in str(request.url) else []
        return httpx.Response(200, json={"meetings": rows})

    with _client(handler) as client:
        out = client.fetch_meetings(NOW - timedelta(days=1), account_email="me@example.com")
    assert out[0]["payload"]["organizer"] == "someone.else@example.com"


def test_plan_gated_responses_raise_ZoomPlanError_not_a_generic_error():
    """The distinction is what lets callers report a capability instead of a
    failure, so it is pinned here."""
    def handler(request):
        return httpx.Response(403, json={"message": "Only available for paid subscription"})

    with _client(handler) as client:
        with pytest.raises(ZoomPlanError):
            client.recordings()


def test_an_ordinary_bad_request_is_still_an_error():
    """The plan sniffing must not swallow real failures."""
    def handler(request):
        return httpx.Response(400, json={"message": "Invalid meeting id"})

    with _client(handler) as client:
        with pytest.raises(ZoomError):
            client.meeting("nope")


# --- writes: the Action Registry contract -----------------------------------


def test_every_zoom_write_is_external_and_therefore_confirmed():
    """external=True is what makes needs_approval_for() demand a preview. A Zoom
    write must never be silent."""
    for key in ("zoom.create_meeting", "zoom.update_meeting", "zoom.delete_meeting"):
        spec = REGISTRY[key]
        assert spec.external is True
        assert spec.needs_approval is True


def test_delete_is_irreversible_and_has_no_undo_function():
    """The registry's own rule: the ABSENCE of a compensation is what makes
    IRREVERSIBLE real rather than a label. Recreating a meeting would mint a new
    join link and could not unsend the cancellation."""
    spec = REGISTRY["zoom.delete_meeting"]
    assert spec.reversibility is Reversibility.IRREVERSIBLE
    assert spec.compensate is None
    assert spec.autonomy_eligible is False


def test_create_and_update_promise_undo_only_because_they_can_deliver_it():
    for key in ("zoom.create_meeting", "zoom.update_meeting"):
        spec = REGISTRY[key]
        assert spec.reversibility is Reversibility.COMPENSATABLE
        assert spec.compensate is not None


def test_the_delete_preview_names_the_consequence():
    spec = REGISTRY["zoom.delete_meeting"]
    preview = spec.preview(spec.params_model(meeting_id="123", topic="Sprint review", notify=True))
    assert preview["irreversible"] is True
    assert "cannot be recalled" in preview["warning"]


def test_the_create_preview_says_plainly_that_nobody_is_invited():
    """Zoom differs from the calendar actions here, and a user should not have to
    guess which behaviour they are getting."""
    spec = REGISTRY["zoom.create_meeting"]
    preview = spec.preview(spec.params_model(topic="Kickoff", start=NOW + timedelta(days=1), duration=30))
    assert preview["notifies"] is False
    assert "Nobody is invited" in preview["effect"]


def test_update_captures_previous_values_so_undo_is_real():
    """The snapshot is what separates a real undo from an aspirational one."""
    calls: list[str] = []

    def handler(request):
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "GET":
            return httpx.Response(200, json=_meeting(topic="Old topic", duration=30, agenda="Old agenda"))
        return httpx.Response(204)

    import app.services.action_registry as ar

    class _Action:
        params = {"meeting_id": "84512345678", "topic": "New topic"}

    client = _client(handler)
    original = ar._zoom_client
    ar._zoom_client = lambda session, action: client
    try:
        result = ar._execute_zoom_update(None, _Action())
    finally:
        ar._zoom_client = original
        client.close()

    assert result["previous"]["topic"] == "Old topic"
    assert result["previous"]["agenda"] == "Old agenda"
    assert result["previous"]["duration"] == 30
    # The read happened BEFORE the write, which is the whole point.
    assert calls[0].startswith("GET")
    assert any(c.startswith("PATCH") for c in calls)


# --- transcripts ------------------------------------------------------------


def test_vtt_becomes_readable_text():
    vtt = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
Alice: Let us start with the deploy.

2
00:00:04.000 --> 00:00:07.000
Bob: It is blocked on review.
"""
    assert _vtt_to_text(vtt) == "Alice: Let us start with the deploy.\nBob: It is blocked on review."


def test_meeting_uuids_with_slashes_are_double_encoded():
    """Zoom's own rule. Getting it wrong yields a mystifying 404."""
    from app.integrations.zoom_client import _encode_uuid

    assert _encode_uuid("abc123==") == "abc123%3D%3D"
    # A leading slash or an embedded // requires encoding twice.
    assert _encode_uuid("/abc//def") == "%252Fabc%252F%252Fdef"
