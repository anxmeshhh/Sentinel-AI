"""Zoom API client (api.zoom.us/v2).

The important work here, exactly as in graph_client, is NORMALIZATION: a Zoom
meeting is reshaped into the same payload dict a Google Calendar or Outlook event
carries - title/start/end/attendee_count/organizer/meet_url/status/url. That is
what lets Zoom meetings flow through the existing CALENDAR_EVENT detector and the
whole Intelligence Core without a single Zoom-aware line downstream.

Two Zoom shapes are worth knowing when reading this:

  * A meeting has BOTH an `id` (numeric, stable, what you address for
    create/update/delete) and a `uuid` (per-OCCURRENCE, what past-meeting and
    recording endpoints key on). They are not interchangeable, and using the
    wrong one is the classic Zoom integration bug.
  * `duration` is minutes, and there is no end time in the list response - the
    end is computed. A recurring meeting with no fixed time has no start_time at
    all, which is why those are skipped rather than guessed at.

Plan-gated endpoints (participants, recordings) raise ZoomPlanError rather than a
generic failure, so callers can report a capability honestly instead of an error.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import structlog

logger = structlog.get_logger("sentinel.zoom")

API_BASE = "https://api.zoom.us/v2"
# Zoom pages at 300 max; meetings are low-volume next to mail, so one or two
# pages covers any realistic account.
PAGE_SIZE = 300
MAX_MEETINGS_PER_SYNC = 600
# How far back recordings are listed. Zoom requires an explicit from/to and caps
# the span at one month per query, so this is also the practical maximum.
RECORDING_WINDOW = timedelta(days=30)


class ZoomError(Exception):
    pass


class ZoomPlanError(ZoomError):
    """The account's plan does not include this capability.

    Distinct from ZoomError on purpose: this is a fact about the account, not a
    failure of the integration, and the UI says so rather than showing an error.
    """


class ZoomScopeError(ZoomError):
    """The token was never granted the scope this call needs (Zoom code 4711).

    Also a fact rather than a failure, but a DIFFERENT fact from ZoomPlanError,
    and worth separating: a missing scope can be fixed by re-consenting with it
    added, whereas a plan limit cannot. Conflating them would tell a user to go
    buy a plan when all they needed was to reconnect - or the reverse.

    Found by live testing: removing the cloud_recording scopes made Zoom answer
    4711 "does not contain scopes", which the plan heuristic did not match, so
    the probe reported "could not tell" about something Zoom had stated exactly.
    """


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class ZoomClient:
    def __init__(self, access_token: str):
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )

    def __enter__(self) -> "ZoomClient":
        return self

    def __exit__(self, *exc) -> None:
        self._client.close()

    def close(self) -> None:
        self._client.close()

    # --- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self._client.request(method, path, **kwargs)
        if response.status_code in (400, 403):
            # Zoom reports both "your plan lacks this" and "your token lacks the
            # scope" as a 400 or 403 with a descriptive body. Read the body
            # rather than guessing from the status, since both codes are also
            # used for ordinary bad requests - and separate the two causes,
            # because the remedies are completely different.
            body = (response.text or "").lower()
            if "does not contain scopes" in body or '"code":4711' in body.replace(" ", ""):
                raise ZoomScopeError(response.text[:300])
            if any(hint in body for hint in ("plan", "subscription", "not available", "no permission", "upgrade")):
                raise ZoomPlanError(response.text[:300])
        if response.status_code == 404:
            raise ZoomError(f"Zoom has no such resource: {path}")
        if response.status_code >= 400:
            logger.warning("zoom_request_failed", path=path, status=response.status_code, body=response.text[:300])
            raise ZoomError(f"Zoom returned {response.status_code}: {response.text[:200]}")
        if not response.content:
            return {}
        return response.json()

    def _paginate(self, path: str, params: dict, key: str, cap: int) -> list[dict]:
        out: list[dict] = []
        token = ""
        while len(out) < cap:
            page = self._request("GET", path, params={**params, "page_size": PAGE_SIZE, **({"next_page_token": token} if token else {})})
            out.extend(page.get(key) or [])
            token = page.get("next_page_token") or ""
            if not token:
                break
        return out[:cap]

    # --- account -----------------------------------------------------------

    def me(self) -> dict:
        """The connected account. `type` is the plan: 1 Basic (free), 2 Licensed
        (Pro+), 3 On-prem - which is what gates recordings and participant
        reports, so it is surfaced rather than interpreted here."""
        data = self._request("GET", "/users/me")
        return {
            "id": data.get("id") or "",
            "email": data.get("email") or "",
            "display_name": " ".join(filter(None, (data.get("first_name"), data.get("last_name")))).strip()
            or data.get("display_name")
            or data.get("email")
            or "",
            "account_id": data.get("account_id") or "",
            "plan_type": data.get("type"),
            "timezone": data.get("timezone") or "",
            "personal_meeting_url": data.get("personal_meeting_url") or "",
        }

    # --- meetings: read ----------------------------------------------------

    def fetch_meetings(self, since: datetime, *, account_email: str = "") -> list[dict]:
        """Upcoming and recently-past meetings, normalized to the CALENDAR_EVENT
        payload every other calendar provider produces.

        Both `upcoming_meetings` and `previous_meetings` are read: the detector
        cares about what is about to start, but a meeting that just finished is
        what makes a recording or a follow-up meaningful. Deduped on id, since a
        meeting can legitimately appear in both around its start time.
        """
        seen: dict[str, dict] = {}
        for list_type in ("upcoming_meetings", "previous_meetings"):
            try:
                rows = self._paginate("/users/me/meetings", {"type": list_type}, "meetings", MAX_MEETINGS_PER_SYNC)
            except ZoomError:
                # One list type failing must not lose the other. `scheduled` is
                # the universally-available fallback shape.
                logger.info("zoom_meeting_list_unavailable", list_type=list_type)
                continue
            for m in rows:
                if m.get("id") is not None:
                    seen.setdefault(str(m["id"]), m)

        out: list[dict] = []
        for raw in seen.values():
            normalized = self._normalize_meeting(raw, account_email=account_email)
            if normalized is None:
                continue
            # Past meetings older than the sync window are not re-ingested; the
            # upsert would be harmless but the work is not free.
            if normalized["occurred_at"] < since - timedelta(days=1):
                continue
            out.append(normalized)
        return out

    def _normalize_meeting(self, m: dict, *, account_email: str = "") -> dict | None:
        """One Zoom meeting -> the provider-neutral calendar payload.

        Returns None for a recurring meeting with no fixed time (Zoom omits
        start_time entirely for those): it has no occurrence to place on a
        timeline, and inventing one would put a fake meeting in front of a user.
        """
        start = _parse(m.get("start_time"))
        if start is None:
            return None
        duration = m.get("duration")
        end = start + timedelta(minutes=duration if isinstance(duration, int) and duration > 0 else 60)
        join_url = m.get("join_url") or ""
        # Zoom often omits host_email from the list response (confirmed live on a
        # freshly created meeting), leaving only an opaque host_id. Falling back
        # to the connected account's own address is not a guess: these are the
        # meetings of THAT account, so its owner is the host. Without this the
        # organizer renders as an unreadable id, or as nothing at all.
        host = m.get("host_email") or account_email or m.get("host_id") or "unknown"
        return {
            "external_id": str(m["id"]),
            "actor": host,
            "occurred_at": start,
            "payload": {
                "title": m.get("topic") or "(no title)",
                "start": start.isoformat(),
                "end": end.isoformat(),
                # Zoom's list response carries no attendee roster - participants
                # are a separate, plan-gated endpoint. Reporting 0 would be a
                # lie, so the key is present-but-null and the detector's
                # `or 0` treats it as "unknown" rather than "nobody".
                "attendee_count": None,
                "attendee_emails": [],
                "organizer": host,
                # Every Zoom meeting has a join link by definition - that is what
                # a Zoom meeting IS. Mapped onto the same provider-neutral key
                # Google's Meet link and Outlook's Teams link already use.
                "has_meeting_link": bool(join_url),
                "meet_url": join_url,
                "status": "cancelled" if (m.get("status") or "") == "cancelled" else "confirmed",
                "url": join_url,
                # Zoom-specific but harmless as payload detail: the uuid is what
                # past-meeting and recording lookups key on, and carrying it here
                # saves a round trip later. Nothing downstream reads it.
                "zoom_uuid": m.get("uuid") or "",
                "zoom_meeting_id": str(m["id"]),
                "timezone": m.get("timezone") or "",
            },
        }

    def meeting(self, meeting_id: str) -> dict:
        """Full detail for one meeting, including the agenda and settings the
        list response omits."""
        m = self._request("GET", f"/meetings/{meeting_id}")
        start = _parse(m.get("start_time"))
        duration = m.get("duration") if isinstance(m.get("duration"), int) else 60
        settings = m.get("settings") or {}
        return {
            "id": str(m.get("id") or meeting_id),
            "uuid": m.get("uuid") or "",
            "topic": m.get("topic") or "",
            "agenda": m.get("agenda") or "",
            "start": start,
            "end": (start + timedelta(minutes=duration)) if start else None,
            "duration": duration,
            "timezone": m.get("timezone") or "",
            "join_url": m.get("join_url") or "",
            "start_url": m.get("start_url") or "",
            "password": m.get("password") or "",
            "host_email": m.get("host_email") or "",
            "status": m.get("status") or "",
            "waiting_room": bool(settings.get("waiting_room")),
            "join_before_host": bool(settings.get("join_before_host")),
            "auto_recording": settings.get("auto_recording") or "none",
        }

    def past_participants(self, meeting_uuid: str) -> list[dict]:
        """Who actually attended. Plan-gated: Zoom restricts this to paid plans,
        so a Basic account raises ZoomPlanError and the UI reports a capability
        rather than an error."""
        rows = self._paginate(
            f"/past_meetings/{_encode_uuid(meeting_uuid)}/participants", {}, "participants", 500
        )
        return [
            {
                "name": p.get("name") or "",
                "email": p.get("user_email") or "",
                "joined_at": _parse(p.get("join_time")),
                "left_at": _parse(p.get("leave_time")),
                "duration": p.get("duration"),
            }
            for p in rows
        ]

    # --- recordings --------------------------------------------------------

    def recordings(self, since: datetime | None = None) -> list[dict]:
        """Cloud recordings, newest first. Plan-gated (cloud recording is not
        part of the free tier), so ZoomPlanError is the expected outcome on a
        Basic account rather than an exceptional one.

        Never stored: this is read live, on request, and the download URLs Zoom
        returns are short-lived and account-scoped.
        """
        now = datetime.now(timezone.utc)
        start = since or (now - RECORDING_WINDOW)
        rows = self._paginate(
            "/users/me/recordings",
            {"from": start.date().isoformat(), "to": now.date().isoformat()},
            "meetings",
            200,
        )
        out = []
        for r in rows:
            files = r.get("recording_files") or []
            out.append({
                "meeting_id": str(r.get("id") or ""),
                "uuid": r.get("uuid") or "",
                "topic": r.get("topic") or "",
                "start": _parse(r.get("start_time")),
                "duration": r.get("duration"),
                "total_size": r.get("total_size"),
                "share_url": r.get("share_url") or "",
                "files": [
                    {
                        "id": f.get("id") or "",
                        "type": f.get("file_type") or "",
                        "extension": f.get("file_extension") or "",
                        "size": f.get("file_size"),
                        "play_url": f.get("play_url") or "",
                        "download_url": f.get("download_url") or "",
                    }
                    for f in files
                ],
                # Zoom delivers an audio transcript as a recording FILE of type
                # TRANSCRIPT (a .VTT), not a separate resource - so "has a
                # transcript" is a property of the file list, not another call.
                "has_transcript": any((f.get("file_type") or "").upper() == "TRANSCRIPT" for f in files),
            })
        return out

    def transcript_text(self, download_url: str) -> str:
        """Fetch a VTT transcript and flatten it to plain text.

        Read on demand and returned to the caller; never written to a Signal.
        The URL is one Zoom itself issued moments earlier in the recording list.
        """
        response = self._client.get(download_url, timeout=60.0)
        if response.status_code >= 400:
            raise ZoomError(f"Could not read the transcript: {response.status_code}")
        return _vtt_to_text(response.text)

    # --- meetings: write ---------------------------------------------------
    #
    # Reached ONLY from the Action Registry. Nothing in this module decides to
    # call them; they are the provider half of an already-confirmed action.

    def create_meeting(self, *, topic: str, start: datetime, duration: int, agenda: str = "", timezone_name: str = "UTC") -> dict:
        body = {
            "topic": topic,
            "type": 2,  # a scheduled meeting with a fixed time
            "start_time": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration": duration,
            "timezone": timezone_name or "UTC",
            "agenda": agenda,
        }
        m = self._request("POST", "/users/me/meetings", json=body)
        return {
            "id": str(m.get("id") or ""),
            "uuid": m.get("uuid") or "",
            "topic": m.get("topic") or topic,
            "join_url": m.get("join_url") or "",
            "start_url": m.get("start_url") or "",
            "start": _parse(m.get("start_time")),
        }

    def update_meeting(self, meeting_id: str, *, topic: str | None = None, start: datetime | None = None,
                       duration: int | None = None, agenda: str | None = None) -> None:
        """Zoom's PATCH returns 204 with no body, so there is nothing to read
        back here - the Action Registry's verify step re-reads the meeting
        instead, which is the stronger check anyway."""
        body: dict = {}
        if topic is not None:
            body["topic"] = topic
        if start is not None:
            body["start_time"] = start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if duration is not None:
            body["duration"] = duration
        if agenda is not None:
            body["agenda"] = agenda
        if not body:
            return
        self._request("PATCH", f"/meetings/{meeting_id}", json=body)

    def delete_meeting(self, meeting_id: str, *, notify: bool = True) -> None:
        self._request(
            "DELETE", f"/meetings/{meeting_id}",
            params={"schedule_for_reminder": str(notify).lower()},
        )


def _encode_uuid(meeting_uuid: str) -> str:
    """Zoom meeting UUIDs can contain `/` and `//`, which break a path segment.
    Zoom's own rule: double-encode when the uuid starts with `/` or contains
    `//`. Getting this wrong yields a confusing 404, so it is done explicitly."""
    from urllib.parse import quote

    if meeting_uuid.startswith("/") or "//" in meeting_uuid:
        return quote(quote(meeting_uuid, safe=""), safe="")
    return quote(meeting_uuid, safe="")


def _vtt_to_text(vtt: str) -> str:
    """WEBVTT -> readable lines, dropping cue numbers and timestamps."""
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or line.isdigit() or "-->" in line:
            continue
        if lines and lines[-1] == line:
            continue  # Zoom repeats a cue when a speaker pauses
        lines.append(line)
    return "\n".join(lines)
