"""Gmail client - metadata only at ingestion time: subject, participants,
timestamp, thread, labels. Body content is never stored - see
fetch_message_body() below, which is the one deliberate, bounded exception:
a live, on-demand, never-persisted fetch used only when a user explicitly
asks for a specific email's content (Mail page click, or a targeted
Assistant question). Nothing that goes through fetch_message_body ever
touches the database.

Hard constraint (same discipline as the GitHub client's diff-stripping):
Gmail's API returns a `snippet` field (a body preview) even in metadata
mode. We explicitly discard it in _normalize_message and never store or
forward it - the message body, in any form, never reaches storage.
"""

import base64
import time
from datetime import datetime, timezone

import httpx
import structlog

logger = structlog.get_logger("sentinel.gmail")

API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_MESSAGES_PER_SYNC = 500  # safety cap - a large mailbox shouldn't turn one sync into thousands of requests
METADATA_HEADERS = ["Subject", "From", "To", "Date"]
MAX_BODY_CHARS = 20_000  # a live-fetched body is bounded before it ever reaches an LLM prompt


class GmailClient:
    def __init__(self, access_token: str, timeout: float = 20.0):
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GmailClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def fetch_messages(self, since: datetime) -> list[dict]:
        message_ids = self._list_message_ids(since)
        messages = []
        for message_id in message_ids[:MAX_MESSAGES_PER_SYNC]:
            metadata = self._fetch_message_metadata(message_id)
            if metadata:
                messages.append(metadata)
        return messages

    def fetch_message_body(self, message_id: str) -> str | None:
        """Live, on-demand, never-persisted body fetch - see module docstring."""
        resp = self._get_with_retry(f"/messages/{message_id}", {"format": "full"})
        return _extract_body(resp.json())

    def search(self, query: str, max_results: int = 20) -> list[dict]:
        """Live search against Gmail's own index using its native query syntax
        (keywords, is:starred, from:x, after:/before:) - unlike browsing the
        locally-ingested Signal cache (mail_query.py), this reaches the whole
        mailbox and Gmail's own full-text index, not just the last
        MAX_MESSAGES_PER_SYNC backfilled messages. Metadata only, same as
        fetch_messages - only fetch_message_body ever reads a body.
        """
        ids: list[str] = []
        page_token: str | None = None
        while len(ids) < max_results:
            params = {"q": query, "maxResults": min(50, max_results - len(ids)), "includeSpamTrash": "true"}
            if page_token:
                params["pageToken"] = page_token
            resp = self._get_with_retry("/messages", params)
            data = resp.json()
            ids.extend(m["id"] for m in data.get("messages", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        messages = []
        for message_id in ids[:max_results]:
            metadata = self._fetch_message_metadata(message_id)
            if metadata:
                messages.append(metadata)
        return messages

    def _list_message_ids(self, since: datetime) -> list[str]:
        ids: list[str] = []
        page_token: str | None = None
        query = f"after:{int(since.timestamp())}"

        while len(ids) < MAX_MESSAGES_PER_SYNC:
            # includeSpamTrash - without it Gmail's default list excludes SPAM
            # and TRASH entirely, so spam mail was silently never even seen.
            params = {"q": query, "maxResults": 100, "includeSpamTrash": "true"}
            if page_token:
                params["pageToken"] = page_token

            resp = self._get_with_retry("/messages", params)
            data = resp.json()
            ids.extend(m["id"] for m in data.get("messages", []))

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return ids

    def _fetch_message_metadata(self, message_id: str) -> dict | None:
        # httpx serializes a list value as repeated query keys, which is
        # exactly the shape Gmail's API expects for repeated metadataHeaders.
        resp = self._get_with_retry(f"/messages/{message_id}", {"format": "metadata", "metadataHeaders": METADATA_HEADERS})
        return _normalize_message(resp.json())

    def _get_with_retry(self, path: str, params: dict, max_retries: int = 3) -> httpx.Response:
        for attempt in range(1, max_retries + 1):
            resp = self._client.get(path, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                logger.warning("gmail_retry", path=path, status=resp.status_code, attempt=attempt)
                time.sleep(min(2**attempt, 10))
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp


def _normalize_message(data: dict) -> dict | None:
    # `snippet` is deliberately never read here - see module docstring.
    headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
    date_header = headers.get("Date")
    if not date_header:
        return None

    return {
        "external_id": data["id"],
        "actor": headers.get("From", "unknown"),
        "occurred_at": _parse_date_header(date_header),
        "payload": {
            "thread_id": data.get("threadId"),
            "subject": headers.get("Subject", "(no subject)"),
            "from": headers.get("From"),
            "to": headers.get("To"),
            "label_ids": data.get("labelIds", []),
        },
    }


def _parse_date_header(value: str) -> datetime:
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _extract_body(data: dict) -> str | None:
    """Walk a full-format message's MIME tree for a readable body.
    Prefers text/plain; falls back to text/html with tags stripped.
    Truncated to MAX_BODY_CHARS before it ever leaves this function.
    """
    payload = data.get("payload") or {}
    plain = _find_part(payload, "text/plain")
    if plain is not None:
        return plain[:MAX_BODY_CHARS]
    html = _find_part(payload, "text/html")
    if html is not None:
        return _strip_html(html)[:MAX_BODY_CHARS]
    return None


def _find_part(part: dict, mime_type: str) -> str | None:
    if part.get("mimeType") == mime_type:
        data = (part.get("body") or {}).get("data")
        if data:
            return _decode_base64url(data)
    for sub_part in part.get("parts", []) or []:
        found = _find_part(sub_part, mime_type)
        if found is not None:
            return found
    return None


def _decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _strip_html(raw_html: str) -> str:
    import html
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()
