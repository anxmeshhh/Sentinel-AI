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

    def fetch_events(self, since: datetime) -> list[dict]:
        events: list[dict] = []
        page_token: str | None = None
        while True:
            params = {
                "timeMin": since.astimezone(timezone.utc).isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 250,
            }
            if page_token:
                params["pageToken"] = page_token

            resp = self._client.get("/calendars/primary/events", params=params)
            if resp.status_code != 200:
                logger.warning("google_calendar_fetch_failed", status=resp.status_code)
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
    start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
    if not start or event.get("status") == "cancelled":
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
