"""Google Calendar client - metadata only: title, attendees, start/end time,
meeting link. Calendar events don't have a "body" the way emails/PRs do, so
there's no separate stripping step here - the event resource itself is
already just metadata.
"""

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
