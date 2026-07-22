"""Google Calendar client - metadata only: title, attendees, start/end time,
meeting link. Calendar events don't have a "body" the way emails/PRs do, so
there's no separate stripping step here - the event resource itself is
already just metadata.

create_event() is the one write operation in this codebase - everything
else, in every client, is read-only. It exists only for the AI Command
orchestrator (services/orchestrator.py), and the orchestrator never calls it
without the user confirming a shown plan first - see that module's docstring.
"""

import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import structlog

logger = structlog.get_logger("sentinel.google_calendar")

API_BASE = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarClient:
    def __init__(self, access_token: str, timeout: float = 20.0):
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GoogleCalendarClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def fetch_events(self, since: datetime, *, until: datetime | None = None, calendar_id: str = "primary") -> list[dict]:
        """calendar_id defaults to the user's own calendar, but any calendar
        the token can read works - e.g. Google's public "Holidays in India"
        calendar (see calendar.readonly's docstring in core/oauth.py for why
        that needs a broader scope than the user's own events do).
        """
        events: list[dict] = []
        page_token: str | None = None
        while True:
            params = {
                "timeMin": since.astimezone(timezone.utc).isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 250,
            }
            if until is not None:
                params["timeMax"] = until.astimezone(timezone.utc).isoformat()
            if page_token:
                params["pageToken"] = page_token

            # Public calendar ids commonly contain '#' and '@' (e.g. Google's
            # own "en.indian#holiday@group.v.calendar.google.com") - quoted
            # with safe="" so '#' doesn't get parsed as a URL fragment
            # delimiter, which silently truncated the request path here.
            resp = self._client.get(f"/calendars/{quote(calendar_id, safe='')}/events", params=params)
            if resp.status_code != 200:
                logger.warning("google_calendar_fetch_failed", status=resp.status_code, calendar_id=calendar_id)
                resp.raise_for_status()

            data = resp.json()
            for event in data.get("items", []):
                normalized = _normalize_event(event)
                if normalized:
                    events.append(normalized)

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return events

    def get_event(self, event_id: str, *, calendar_id: str = "primary") -> dict | None:
        """Read one event back by id.

        Exists for verification (Module 10): an action is only SUCCEEDED once
        the change has been confirmed to exist, not when the write call
        returned. A 404 here is a definite answer - the event is not there -
        while any other error is not, so it raises and the caller records
        UNKNOWN rather than claiming failure.
        """
        resp = self._client.get(f"/calendars/{calendar_id}/events/{event_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def create_event(
        self,
        *,
        title: str,
        start: datetime,
        end: datetime,
        attendee_emails: list[str] | None = None,
        create_meet_link: bool = False,
    ) -> dict:
        """The one write call in this codebase - see module docstring."""
        body: dict = {
            "summary": title,
            "start": {"dateTime": start.astimezone(timezone.utc).isoformat()},
            "end": {"dateTime": end.astimezone(timezone.utc).isoformat()},
        }
        if attendee_emails:
            body["attendees"] = [{"email": e} for e in attendee_emails]

        params = {}
        if create_meet_link:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
            params["conferenceDataVersion"] = 1

        resp = self._client.post("/calendars/primary/events", params=params, json=body)
        if resp.status_code >= 400:
            logger.warning("google_calendar_create_event_failed", status=resp.status_code, body=resp.text[:500])
            resp.raise_for_status()

        event = resp.json()
        meet_link = event.get("hangoutLink") or _extract_conference_link(event)
        return {
            "id": event["id"],
            "title": event.get("summary", title),
            "start": event.get("start", {}).get("dateTime"),
            "end": event.get("end", {}).get("dateTime"),
            "attendee_emails": attendee_emails or [],
            "meet_link": meet_link,
            "url": event.get("htmlLink"),
        }


def _normalize_event(event: dict) -> dict | None:
    # Cancelled events are still synced (with status carried through), not
    # dropped - dropping them meant a cancellation on Google's side never
    # reached our cache, so a stale "still happening" row would sit there
    # forever. Only a genuinely unusable event (no start time at all) is skipped.
    start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
    if not start:
        return None

    attendees = event.get("attendees", [])
    meet_link = event.get("hangoutLink") or _extract_conference_link(event)

    return {
        "external_id": event["id"],
        "actor": (event.get("organizer") or {}).get("email", "unknown"),
        "occurred_at": _parse_ts(start),
        "payload": {
            "title": event.get("summary", "(no title)"),
            "start": start,
            "end": event.get("end", {}).get("dateTime") or event.get("end", {}).get("date"),
            "attendee_count": len(attendees),
            "attendee_emails": [a.get("email") for a in attendees if a.get("email")],
            "organizer": (event.get("organizer") or {}).get("email"),
            "has_meeting_link": bool(meet_link),
            "meet_url": meet_link,
            "status": event.get("status", "confirmed"),
            "url": event.get("htmlLink"),
        },
    }


def _extract_conference_link(event: dict) -> str | None:
    conference_data = event.get("conferenceData") or {}
    for entry_point in conference_data.get("entryPoints", []):
        if entry_point.get("entryPointType") == "video":
            return entry_point.get("uri")
    return None


def _parse_ts(value: str) -> datetime:
    if "T" not in value:
        # all-day event: date only, e.g. "2026-07-18"
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
