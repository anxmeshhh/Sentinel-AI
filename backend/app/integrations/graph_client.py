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

    # --- WRITES ----------------------------------------------------------
    #
    # Every method here changes something in the real Microsoft service. None
    # of them is called from a route directly: they are only ever reached from
    # an ActionSpec's execute/compensate in services/action_registry.py, which
    # is the one place writes are allow-listed, validated, risk-classified,
    # confirmed and audited. That is what keeps "the frontend never writes to
    # Graph" true structurally rather than by convention.
    def _request(self, method: str, path: str, json: dict | None = None) -> httpx.Response:
        resp = self._client.request(method, path, json=json)
        resp.raise_for_status()
        return resp

    def message(self, message_id: str) -> dict:
        """One message, including its body - fetched live for the reader and
        never stored (the same posture as the Gmail client)."""
        resp = self._get_with_retry(
            f"/me/messages/{message_id}",
            {"$select": "id,subject,from,toRecipients,body,receivedDateTime,isRead,flag,webLink"},
        )
        m = resp.json()
        return {
            "id": m.get("id"),
            "subject": m.get("subject") or "(no subject)",
            "from": _addr(m.get("from")),
            "to": ", ".join(a for a in (_addr(r) for r in m.get("toRecipients", [])) if a) or None,
            "body_html": (m.get("body") or {}).get("content") or "",
            "body_type": (m.get("body") or {}).get("contentType") or "html",
            "received_at": _parse(m.get("receivedDateTime")),
            "is_read": bool(m.get("isRead")),
            "flagged": ((m.get("flag") or {}).get("flagStatus") or "").lower() == "flagged",
            "url": m.get("webLink"),
        }

    def set_message_read(self, message_id: str, is_read: bool) -> dict:
        self._request("PATCH", f"/me/messages/{message_id}", {"isRead": is_read})
        return {"message_id": message_id, "is_read": is_read}

    def set_message_flag(self, message_id: str, flagged: bool) -> dict:
        status = "flagged" if flagged else "notFlagged"
        self._request("PATCH", f"/me/messages/{message_id}", {"flag": {"flagStatus": status}})
        return {"message_id": message_id, "flagged": flagged}

    def create_draft(self, *, subject: str, to: list[str], body: str) -> dict:
        """A real draft in the user's Outlook - visible in Outlook itself, and
        deletable, which is what makes this reversible."""
        payload = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to],
        }
        created = self._request("POST", "/me/messages", payload).json()
        return {"draft_id": created.get("id"), "subject": subject, "to": to, "url": created.get("webLink")}

    def create_reply_draft(self, message_id: str, comment: str) -> dict:
        """A reply draft on the real thread, so it keeps its conversation."""
        created = self._request("POST", f"/me/messages/{message_id}/createReply", {"comment": comment}).json()
        return {"draft_id": created.get("id"), "replied_to": message_id, "url": created.get("webLink")}



    # --- OneDrive browse + writes ----------------------------------------
    def _item_out(self, i: dict) -> dict:
        return {
            "id": i.get("id"),
            "name": i.get("name") or "(unnamed)",
            "is_folder": "folder" in i,
            "child_count": ((i.get("folder") or {}).get("childCount") if "folder" in i else None),
            "size": i.get("size"),
            "mime_type": ((i.get("file") or {}).get("mimeType")),
            "modified_at": _parse(i.get("lastModifiedDateTime")),
            "modified_by": (((i.get("lastModifiedBy") or {}).get("user") or {}).get("displayName") or ""),
            "shared": bool(i.get("shared")),
            "parent_id": ((i.get("parentReference") or {}).get("id")),
            "url": i.get("webUrl"),
        }

    def list_children(self, folder_id: str | None = None, cap: int = 200) -> list[dict]:
        """One folder's contents. None means the drive root."""
        path = "/me/drive/root/children" if not folder_id else f"/me/drive/items/{folder_id}/children"
        rows = self._paginate(path, {"$top": "50"}, cap)
        items = [self._item_out(i) for i in rows]
        # Folders first, then files, each alphabetically - how a file browser reads.
        items.sort(key=lambda i: (not i["is_folder"], i["name"].lower()))
        return items

    def get_item(self, item_id: str) -> dict:
        return self._item_out(self._get_with_retry(f"/me/drive/items/{item_id}").json())

    def search_drive(self, query: str, cap: int = 100) -> list[dict]:
        safe = query.replace("'", "''")
        rows = self._paginate(f"/me/drive/root/search(q='{safe}')", {"$top": "50"}, cap)
        return [self._item_out(i) for i in rows]

    def create_folder(self, name: str, parent_id: str | None = None) -> dict:
        path = "/me/drive/root/children" if not parent_id else f"/me/drive/items/{parent_id}/children"
        payload = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
        return self._item_out(self._request("POST", path, payload).json())

    def upload_text_file(self, name: str, content: str, parent_id: str | None = None) -> dict:
        """Small text uploads only - the content travels as an action parameter,
        so this is for notes and documents a person typed, not binaries."""
        base = "/me/drive/root" if not parent_id else f"/me/drive/items/{parent_id}"
        resp = self._client.put(
            f"{base}:/{name}:/content",
            content=content.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
        )
        resp.raise_for_status()
        return self._item_out(resp.json())

    def rename_item(self, item_id: str, new_name: str) -> dict:
        return self._item_out(self._request("PATCH", f"/me/drive/items/{item_id}", {"name": new_name}).json())

    def move_item(self, item_id: str, new_parent_id: str) -> dict:
        payload = {"parentReference": {"id": new_parent_id}}
        return self._item_out(self._request("PATCH", f"/me/drive/items/{item_id}", payload).json())

    def delete_item(self, item_id: str) -> None:
        """Graph moves the item to the OneDrive recycle bin rather than
        destroying it - recoverable in OneDrive, but not through this API."""
        self._request("DELETE", f"/me/drive/items/{item_id}")

    # --- OneNote browse + writes -----------------------------------------
    def notebooks(self) -> list[dict]:
        return [
            {"id": n["id"], "name": n.get("displayName") or "(unnamed notebook)", "url": (n.get("links") or {}).get("oneNoteWebUrl", {}).get("href")}
            for n in self._paginate("/me/onenote/notebooks", {"$top": "50"}, 50)
        ]

    def sections(self, notebook_id: str) -> list[dict]:
        return [
            {"id": s["id"], "name": s.get("displayName") or "(unnamed section)", "notebook_id": notebook_id}
            for s in self._paginate(f"/me/onenote/notebooks/{notebook_id}/sections", {"$top": "50"}, 50)
        ]

    def pages(self, section_id: str, cap: int = 100) -> list[dict]:
        params = {"$select": "id,title,createdDateTime,lastModifiedDateTime,links", "$orderby": "lastModifiedDateTime desc", "$top": "50"}
        return [
            {
                "id": p["id"],
                "title": p.get("title") or "(untitled page)",
                "modified_at": _parse(p.get("lastModifiedDateTime")),
                "url": ((p.get("links") or {}).get("oneNoteWebUrl") or {}).get("href"),
            }
            for p in self._paginate(f"/me/onenote/sections/{section_id}/pages", params, cap)
        ]

    def page_content(self, page_id: str) -> str:
        """The page's HTML. Fetched live and never stored, except transiently as
        an undo snapshot when a write is about to change it."""
        resp = self._get_with_retry(f"/me/onenote/pages/{page_id}/content")
        return resp.text

    def create_page(self, section_id: str, title: str, body: str) -> dict:
        """OneNote takes a full HTML document, not JSON."""
        html = (
            "<!DOCTYPE html><html><head>"
            f"<title>{title}</title></head><body>"
            f"<p>{body}</p>"
            "</body></html>"
        )
        resp = self._client.post(
            f"/me/onenote/sections/{section_id}/pages",
            content=html.encode("utf-8"),
            headers={"Content-Type": "text/html"},
        )
        resp.raise_for_status()
        created = resp.json()
        return {
            "id": created.get("id"),
            "title": created.get("title") or title,
            "url": ((created.get("links") or {}).get("oneNoteWebUrl") or {}).get("href"),
        }

    def patch_page(self, page_id: str, commands: list[dict]) -> None:
        """OneNote edits are a list of commands (append/replace on a target),
        not a document PUT."""
        resp = self._client.patch(
            f"/me/onenote/pages/{page_id}/content",
            json=commands,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

    def delete_page(self, page_id: str) -> None:
        self._request("DELETE", f"/me/onenote/pages/{page_id}")

    # --- To Do writes ----------------------------------------------------
    def _task_out(self, t: dict, list_id: str, list_name: str = "") -> dict:
        due = t.get("dueDateTime") or {}
        return {
            "id": t.get("id"),
            "list_id": list_id,
            "list": list_name,
            "title": t.get("title") or "(untitled task)",
            "status": t.get("status") or "notStarted",
            "importance": (t.get("importance") or "normal").lower(),
            "completed": (t.get("status") == "completed") or bool(t.get("completedDateTime")),
            "due_at": _parse(due.get("dateTime")) if due else None,
            "body": ((t.get("body") or {}).get("content") or "").strip(),
        }

    def _due_payload(self, due):
        if due is None:
            return None
        return {"dateTime": due.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000"), "timeZone": "UTC"}

    def task_lists(self) -> list[dict]:
        return [
            {"id": l["id"], "name": l.get("displayName") or "Tasks", "default": bool(l.get("wellknownListName") == "defaultList")}
            for l in self._paginate("/me/todo/lists", {"$top": "25"}, 25)
        ]

    def get_task(self, list_id: str, task_id: str) -> dict:
        # No $select: Graph rejects $select=title on todoTask (verified live).
        resp = self._get_with_retry(f"/me/todo/lists/{list_id}/tasks/{task_id}")
        return self._task_out(resp.json(), list_id)

    def create_task(self, list_id: str, *, title: str, due=None, importance: str = "normal", body: str | None = None) -> dict:
        payload: dict = {"title": title, "importance": importance}
        if due is not None:
            payload["dueDateTime"] = self._due_payload(due)
        if body:
            payload["body"] = {"contentType": "text", "content": body}
        created = self._request("POST", f"/me/todo/lists/{list_id}/tasks", payload).json()
        return self._task_out(created, list_id)

    def update_task(self, list_id: str, task_id: str, *, title=None, due=..., importance=None, completed=None) -> dict:
        """`due` uses a sentinel so None can mean "clear the due date", which is
        a real edit and not the same as "leave it alone"."""
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if importance is not None:
            payload["importance"] = importance
        if due is not ...:
            payload["dueDateTime"] = self._due_payload(due)
        if completed is not None:
            payload["status"] = "completed" if completed else "notStarted"
        if not payload:
            return self.get_task(list_id, task_id)
        updated = self._request("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}", payload).json()
        return self._task_out(updated, list_id)

    def delete_task(self, list_id: str, task_id: str) -> None:
        self._request("DELETE", f"/me/todo/lists/{list_id}/tasks/{task_id}")

    # --- Calendar writes -------------------------------------------------
    def _event_body(self, *, title, start, end, attendee_emails, online: bool = False, body: str | None = None) -> dict:
        payload: dict = {
            "subject": title,
            "start": {"dateTime": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
            "end": {"dateTime": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
        }
        if attendee_emails:
            payload["attendees"] = [
                {"emailAddress": {"address": a}, "type": "required"} for a in attendee_emails
            ]
        if online:
            # Teams link on a work/school account; harmless (ignored) elsewhere.
            payload["isOnlineMeeting"] = True
            payload["onlineMeetingProvider"] = "teamsForBusiness"
        if body is not None:
            payload["body"] = {"contentType": "Text", "content": body}
        return payload

    def _event_out(self, e: dict) -> dict:
        start = _parse((e.get("start") or {}).get("dateTime"))
        return {
            "id": e.get("id"),
            "title": e.get("subject") or "(no title)",
            "start": start,
            "end": _parse((e.get("end") or {}).get("dateTime")),
            "attendee_emails": [
                (a.get("emailAddress") or {}).get("address")
                for a in e.get("attendees", [])
                if (a.get("emailAddress") or {}).get("address")
            ],
            "organizer": ((e.get("organizer") or {}).get("emailAddress") or {}).get("address"),
            "online": bool(e.get("isOnlineMeeting")),
            "join_url": (e.get("onlineMeeting") or {}).get("joinUrl"),
            "cancelled": bool(e.get("isCancelled")),
            "url": e.get("webUrl"),
        }

    def get_event(self, event_id: str) -> dict:
        resp = self._get_with_retry(f"/me/events/{event_id}", {"$select": _EVENT_SELECT})
        return self._event_out(resp.json())

    def create_event(self, *, title, start, end, attendee_emails=None, online=False, body=None) -> dict:
        payload = self._event_body(
            title=title, start=start, end=end,
            attendee_emails=attendee_emails or [], online=online, body=body,
        )
        return self._event_out(self._request("POST", "/me/events", payload).json())

    def update_event(self, event_id: str, *, title=None, start=None, end=None, attendee_emails=None) -> dict:
        """PATCH only what changed. Attendees are replaced wholesale when given,
        which is Graph's own semantics - so the caller passes the full list."""
        payload: dict = {}
        if title is not None:
            payload["subject"] = title
        if start is not None:
            payload["start"] = {"dateTime": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}
        if end is not None:
            payload["end"] = {"dateTime": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"}
        if attendee_emails is not None:
            payload["attendees"] = [{"emailAddress": {"address": a}, "type": "required"} for a in attendee_emails]
        if not payload:
            return self.get_event(event_id)
        return self._event_out(self._request("PATCH", f"/me/events/{event_id}", payload).json())

    def cancel_event(self, event_id: str, comment: str = "") -> None:
        """As organizer: cancels AND notifies every attendee. That notification
        is why this is treated as irreversible - it cannot be unsent."""
        self._request("POST", f"/me/events/{event_id}/cancel", {"comment": comment} if comment else {})

    def delete_event(self, event_id: str) -> None:
        self._request("DELETE", f"/me/events/{event_id}")

    def send_draft(self, message_id: str) -> None:
        """Send an existing draft. Two steps (create draft, then send it) rather
        than Graph's one-shot /me/sendMail, because the draft gives the audit
        trail a real message id BEFORE anything leaves the mailbox - and if the
        send fails, what exists is a draft, not a mystery."""
        self._request("POST", f"/me/messages/{message_id}/send")

    def find_sent(self, subject: str, since: datetime, cap: int = 10) -> list[dict]:
        """Look for a just-sent message in Sent Items - the only honest way to
        verify a send, since Graph's send returns 202 with no body and the
        message id changes when it moves out of Drafts."""
        resp = self._get_with_retry(
            "/me/mailFolders/sentitems/messages",
            {"$select": "id,subject,sentDateTime,toRecipients", "$orderby": "sentDateTime desc", "$top": str(cap)},
        )
        out = []
        for m in resp.json().get("value", []):
            sent_at = _parse(m.get("sentDateTime"))
            if (m.get("subject") or "") == subject and sent_at is not None and sent_at >= since:
                out.append({"id": m.get("id"), "subject": m.get("subject"), "sent_at": sent_at})
        return out

    def delete_message(self, message_id: str) -> None:
        """Used to undo a draft. Graph moves it to Deleted Items rather than
        destroying it, which is the gentler behaviour for a compensation."""
        self._request("DELETE", f"/me/messages/{message_id}")

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
            # No $select here, deliberately: Graph REJECTS `$select=title` on
            # todoTask with 400 "Invalid request" - verified field by field
            # against the live API. A task is a small object, so requesting the
            # whole thing costs nothing and avoids a quirk that would otherwise
            # fail every To Do sync.
            rows = self._paginate(f"/me/todo/lists/{list_id}/tasks", {"$top": "50"}, cap)
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
