"""Microsoft Graph client - one client for all Microsoft 365 services, since
Graph is a single unified API (unlike Google's per-service clients).

Metadata only at ingestion time, matching Gmail/Calendar's privacy posture: it
requests just the fields the detectors need ($select), never message bodies.

The important work here is NORMALIZATION: an Outlook message is reshaped into the
exact same payload dict a Gmail signal carries, and an Outlook event into the
exact Google Calendar shape - including synthesizing Gmail-style label_ids
(UNREAD/IMPORTANT/STARRED) from Outlook's isRead/importance/flag. That is what
lets Outlook flow through the existing EMAIL and CALENDAR_EVENT detectors, and
the whole Intelligence Core, with zero downstream change.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

import httpx
import structlog

logger = structlog.get_logger("sentinel.graph")

API_BASE = "https://graph.microsoft.com/v1.0"
MAX_MESSAGES_PER_SYNC = 200
MAX_EVENTS_PER_SYNC = 250
CALENDAR_HORIZON = timedelta(days=60)  # upcoming window that meeting detection cares about

_MESSAGE_SELECT = "id,conversationId,subject,from,toRecipients,isRead,importance,flag,inferenceClassification,receivedDateTime,webLink"
_EVENT_SELECT = "id,subject,start,end,attendees,organizer,isOnlineMeeting,onlineMeeting,isCancelled,showAs,webLink"


class GraphError(Exception):
    pass


def _addr(recipient: dict | None) -> str | None:
    if not recipient:
        return None
    ea = recipient.get("emailAddress") or {}
    name, addr = ea.get("name"), ea.get("address")
    if name and addr:
        return f"{name} <{addr}>"
    return addr or name


def _labels_for(message: dict) -> list[str]:
    """Synthesize the Gmail-style labels the EMAIL detectors read, from Outlook's
    native fields. This is the whole normalization trick in one function."""
    labels: list[str] = []
    if not message.get("isRead", True):
        labels.append("UNREAD")
    if (message.get("importance") or "").lower() == "high":
        labels.append("IMPORTANT")
    if ((message.get("flag") or {}).get("flagStatus") or "").lower() == "flagged":
        labels.append("STARRED")
    return labels


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    raw = ts.replace("Z", "+00:00")
    # Graph frequently returns 7-digit fractional seconds ("...00.0000000"),
    # which datetime.fromisoformat rejects on older CPython; truncate to 6.
    raw = re.sub(r"(\.\d{6})\d+", r"\1", raw)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class GraphClient:
    def __init__(self, access_token: str, timeout: float = 20.0):
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={
                "Authorization": f"Bearer {access_token}",
                # Ask Graph to return all dateTimes in UTC so we never have to
                # reconcile per-event timeZone strings.
                "Prefer": 'outlook.timezone="UTC"',
            },
            timeout=timeout,
        )

    def __enter__(self) -> "GraphClient":
        return self

    def __exit__(self, *exc) -> None:
        self._client.close()

    def _get_with_retry(self, path_or_url: str, params: dict | None = None, max_retries: int = 3) -> httpx.Response:
        for attempt in range(max_retries + 1):
            resp = self._client.get(path_or_url, params=params)
            if resp.status_code == 429 and attempt < max_retries:
                wait = int(resp.headers.get("Retry-After", "2"))
                logger.warning("graph_throttled", attempt=attempt, wait=wait)
                time.sleep(min(wait, 10))
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp

    def _paginate(self, path: str, params: dict, cap: int) -> list[dict]:
        items: list[dict] = []
        next_url: str | None = path
        first = True
        while next_url and len(items) < cap:
            resp = self._get_with_retry(next_url, params if first else None)
            data = resp.json()
            items.extend(data.get("value", []))
            next_url = data.get("@odata.nextLink")
            first = False
        return items[:cap]

    # --- Outlook Mail -> EMAIL signals -----------------------------------
    def fetch_messages(self, since: datetime) -> list[dict]:
        since_iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {
            "$select": _MESSAGE_SELECT,
            "$filter": f"receivedDateTime ge {since_iso}",
            "$orderby": "receivedDateTime desc",
            "$top": "50",
        }
        out: list[dict] = []
        for m in self._paginate("/me/messages", params, MAX_MESSAGES_PER_SYNC):
            out.append({
                "external_id": m["id"],
                "actor": _addr(m.get("from")) or "unknown",
                "occurred_at": _parse(m.get("receivedDateTime")),
                "payload": {
                    "thread_id": m.get("conversationId"),
                    "subject": m.get("subject") or "(no subject)",
                    "from": _addr(m.get("from")),
                    "to": ", ".join(a for a in (_addr(r) for r in m.get("toRecipients", [])) if a) or None,
                    "label_ids": _labels_for(m),
                    # Outlook's Focused/Other split is the closest native signal
                    # to Gmail's bulk heuristic.
                    "is_bulk": (m.get("inferenceClassification") or "").lower() == "other",
                    "url": m.get("webLink"),
                },
            })
        return out

    # --- Outlook Calendar -> CALENDAR_EVENT signals ----------------------
    def fetch_events(self, since: datetime) -> list[dict]:
        now = datetime.now(timezone.utc)
        params = {
            "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDateTime": (now + CALENDAR_HORIZON).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "$select": _EVENT_SELECT,
            "$orderby": "start/dateTime",
            "$top": "50",
        }
        out: list[dict] = []
        for e in self._paginate("/me/calendarView", params, MAX_EVENTS_PER_SYNC):
            start = _parse((e.get("start") or {}).get("dateTime"))
            if start is None:
                continue
            attendees = [
                (a.get("emailAddress") or {}).get("address")
                for a in e.get("attendees", [])
                if (a.get("emailAddress") or {}).get("address")
            ]
            organizer = (e.get("organizer") or {}).get("emailAddress", {}).get("address")
            join_url = (e.get("onlineMeeting") or {}).get("joinUrl")
            has_link = bool(e.get("isOnlineMeeting")) or bool(join_url)
            out.append({
                "external_id": e["id"],
                "actor": organizer or "unknown",
                "occurred_at": start,
                "payload": {
                    "title": e.get("subject") or "(no title)",
                    "start": start.isoformat(),
                    "end": (_parse((e.get("end") or {}).get("dateTime")) or start).isoformat(),
                    "attendee_count": len(attendees),
                    "attendee_emails": attendees,
                    "organizer": organizer,
                    "has_meeting_link": has_link,
                    "meet_url": join_url,
                    "status": "cancelled" if e.get("isCancelled") else (e.get("showAs") or "confirmed"),
                    "url": e.get("webLink"),
                },
            })
        return out
