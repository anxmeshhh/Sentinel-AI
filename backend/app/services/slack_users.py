"""Slack user id -> display name, cached.

A finding that reads "@jess is blocked" is worth far more than "U0197ABC is
blocked", but resolving names must not cost an API call per message. So the
workspace directory is fetched once and cached per team for an hour, in-process
- the worker is long-lived, and a stale name for an hour is harmless. Name
resolution is always best-effort: if the lookup fails, ids stand in and
ingestion is never blocked by it.
"""

import re
from datetime import datetime, timedelta, timezone

import structlog

logger = structlog.get_logger("sentinel.slack_users")

_CACHE: dict[str, tuple[dict[str, str], datetime]] = {}
_TTL = timedelta(hours=1)
_MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)>")


def directory(client, team_id: str) -> dict[str, str]:
    """{user_id: name} for the workspace, cached per team. Returns an empty map
    (ids will stand in) rather than raising if Slack can't be reached."""
    now = datetime.now(timezone.utc)
    hit = _CACHE.get(team_id)
    if hit and now - hit[1] < _TTL:
        return hit[0]
    try:
        mapping = {u["id"]: u["name"] for u in client.list_users()}
    except Exception as exc:
        logger.warning("slack_user_directory_failed", error=str(exc)[:120])
        return hit[0] if hit else {}
    _CACHE[team_id] = (mapping, now)
    return mapping


def humanize(text: str | None, mapping: dict[str, str]) -> str:
    """Rewrite <@U123> tokens in message text to @name for readable evidence."""
    if not text:
        return text or ""
    return _MENTION_RE.sub(lambda m: "@" + mapping.get(m.group(1), m.group(1)), text)


def name_for(user_id: str | None, mapping: dict[str, str]) -> str:
    return mapping.get(user_id or "", user_id or "")
