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


def fetch_account_identity(access_token: str) -> str:
    """The signed-in account's address, for the ONE moment we need it: right
    after connecting, to label the grant's child connections (Connection.org).

    Deliberately NOT sourced from an ID token - see core/oauth.py's
    microsoft_data registration for why we request no ID token at all. Asking
    Graph directly is authoritative for both account kinds this app supports:
    `mail` for a normal mailbox, falling back to `userPrincipalName` (always
    present, even when `mail` is null - which happens for some personal
    Microsoft accounts with no primary SMTP address set).
    """
    resp = httpx.get(
        f"{API_BASE}/me", params={"$select": "mail,userPrincipalName"},
        headers={"Authorization": f"Bearer {access_token}"}, timeout=20.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("mail") or data.get("userPrincipalName") or "unknown-microsoft-account"


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

    # --- Microsoft Teams -------------------------------------------------
    #
    # Two tiers, on purpose. Metadata (teams, channels, members) needs only the
    # ordinary Team.ReadBasic.All / Channel.ReadBasic.All scopes. Channel
    # MESSAGES need ChannelMessage.Read.All, which Microsoft classifies as a
    # PROTECTED API: it requires tenant admin consent and, at scale, a licensed
    # export model. So message access is treated as a capability that may or may
    # not be present, never assumed - see channel_messages().
    def list_joined_teams(self) -> list[dict]:
        """The teams the signed-in user belongs to."""
        params = {"$select": "id,displayName,description"}
        return [
            {"id": t["id"], "name": t.get("displayName") or "(unnamed team)", "description": t.get("description") or ""}
            for t in self._paginate("/me/joinedTeams", params, 100)
        ]

    def list_channels(self, team_id: str) -> list[dict]:
        params = {"$select": "id,displayName,description,membershipType"}
        return [
            {
                "id": c["id"],
                "name": c.get("displayName") or "(unnamed channel)",
                "description": c.get("description") or "",
                "membership_type": c.get("membershipType") or "standard",
            }
            for c in self._paginate(f"/teams/{team_id}/channels", params, 200)
        ]

    def list_channel_members(self, team_id: str, channel_id: str) -> list[dict]:
        """Members of one channel. Best-effort: private-channel membership can be
        restricted even when the channel is listable, so callers treat a failure
        as "unknown membership" rather than an error."""
        rows = self._paginate(f"/teams/{team_id}/channels/{channel_id}/members", {}, 200)
        return [{"id": m.get("userId") or m.get("id"), "name": m.get("displayName") or ""} for m in rows]

    def channel_messages(self, team_id: str, channel_id: str, since: datetime, cap: int = 200) -> tuple[list[dict], bool]:
        """(messages, allowed). `allowed` is False when the tenant has not granted
        the protected ChannelMessage.Read.All permission.

        Returning a flag instead of raising is deliberate: no message access is a
        normal, expected configuration - not a failure - and the caller degrades
        to metadata-only monitoring rather than marking the sync broken.
        """
        params = {"$top": "50"}
        try:
            raw = self._paginate(f"/teams/{team_id}/channels/{channel_id}/messages", params, cap)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                logger.info("graph_teams_messages_forbidden", team_id=team_id, channel_id=channel_id)
                return [], False
            raise

        out: list[dict] = []
        for m in raw:
            created = _parse(m.get("createdDateTime"))
            if created is None or created < since:
                continue
            body = (m.get("body") or {}).get("content") or ""
            frm = ((m.get("from") or {}).get("user") or {})
            out.append({
                "id": m.get("id"),
                "created_at": created,
                "actor_id": frm.get("id") or "",
                "actor_name": frm.get("displayName") or "",
                "body_html": body,
                "mentions": m.get("mentions") or [],
                "importance": (m.get("importance") or "normal").lower(),
                "message_type": (m.get("messageType") or "message").lower(),
                "reply_count": len(m.get("replies") or []),
                "url": m.get("webUrl"),
            })
        return out, True

    # --- OneDrive -> DRIVE_FILE signals ----------------------------------
    def recent_files(self, since: datetime, cap: int = 150) -> list[dict]:
        """Files CHANGED since the checkpoint - metadata only, never content.

        Uses the drive's delta feed, which is the incremental primitive here:
        it returns what actually changed rather than paging the whole tree, so a
        sync stays bounded no matter how large the drive is.
        """
        params = {"$top": "50"}
        raw = self._paginate("/me/drive/root/delta", params, cap * 3)
        out: list[dict] = []
        for f in raw:
            if f.get("deleted") or f.get("folder"):
                continue  # folders and tombstones are not document activity
            modified = _parse(f.get("lastModifiedDateTime"))
            if modified is None or modified < since:
                continue
            by = ((f.get("lastModifiedBy") or {}).get("user") or {})
            created_by = ((f.get("createdBy") or {}).get("user") or {})
            out.append({
                "id": f["id"],
                "name": f.get("name") or "(unnamed)",
                "modified_at": modified,
                "modified_by": by.get("displayName") or "",
                "created_by": created_by.get("displayName") or "",
                "mime_type": ((f.get("file") or {}).get("mimeType")),
                "size": f.get("size"),
                # Presence of `shared` is Graph's own marker that the item is
                # not private to this account - the closest thing to a
                # collaboration signal available without extra permissions.
                "shared": bool(f.get("shared")),
                "url": f.get("webUrl"),
            })
        out.sort(key=lambda x: x["modified_at"], reverse=True)
        return out[:cap]

    # --- OneNote -> NOTE signals -----------------------------------------
    def recent_notes(self, since: datetime, cap: int = 100) -> list[dict]:
        """Note pages modified since the checkpoint. Titles and timestamps
        only - the page's HTML content is never fetched."""
        params = {
            "$select": "id,title,createdDateTime,lastModifiedDateTime,links,parentNotebook,parentSection",
            "$orderby": "lastModifiedDateTime desc",
            "$top": "50",
        }
        out: list[dict] = []
        for p in self._paginate("/me/onenote/pages", params, cap):
            modified = _parse(p.get("lastModifiedDateTime"))
            if modified is None or modified < since:
                continue
            links = p.get("links") or {}
            out.append({
                "id": p["id"],
                "title": p.get("title") or "(untitled page)",
                "modified_at": modified,
                "notebook": ((p.get("parentNotebook") or {}).get("displayName") or ""),
                "section": ((p.get("parentSection") or {}).get("displayName") or ""),
                "url": ((links.get("oneNoteWebUrl") or {}).get("href")),
            })
        return out

    # --- Microsoft To Do -> TASK signals ----------------------------------
    def tasks(self, cap: int = 300) -> list[dict]:
        """Every task across the account's To Do lists.

        Deliberately NOT filtered by a `since` checkpoint: a task's importance
        comes from its DUE DATE, not from when it was last edited. A task
        created last month and due today must surface today, which an
        incremental-by-modification fetch would miss entirely.
        """
        out: list[dict] = []
        lists = self._paginate("/me/todo/lists", {"$top": "25"}, 25)
        for lst in lists:
            list_id, list_name = lst.get("id"), lst.get("displayName") or "Tasks"
            if not list_id:
                continue
            rows = self._paginate(
                f"/me/todo/lists/{list_id}/tasks",
                {"$top": "50", "$select": "id,title,status,importance,dueDateTime,completedDateTime,createdDateTime,lastModifiedDateTime"},
                cap,
            )
            for t in rows:
                due = t.get("dueDateTime") or {}
                out.append({
                    "id": t["id"],
                    "title": t.get("title") or "(untitled task)",
                    "list": list_name,
                    "status": (t.get("status") or "notStarted"),
                    "importance": (t.get("importance") or "normal").lower(),
                    "due_at": _parse(due.get("dateTime")) if due else None,
                    "completed_at": _parse((t.get("completedDateTime") or {}).get("dateTime")),
                    "created_at": _parse(t.get("createdDateTime")),
                    "modified_at": _parse(t.get("lastModifiedDateTime")),
                })
            if len(out) >= cap:
                break
        return out[:cap]

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
