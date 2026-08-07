"""Deterministic extraction of operational signals from chat messages, for ANY
conversation provider.

Generalized from services/slack_signals.py when Microsoft Teams became the
second chat provider (the N=2 rule this codebase follows). What is genuinely
shared lives here: the operational lexicon, the "is this a system message"
filter, and the shape of the answer. What genuinely differs is each provider's
*mention grammar* - Slack encodes mentions as `<@U123>` tokens, Teams as
`<at id="0">Name</at>` HTML - so that stays per-provider, behind one interface.

Pure functions, no network and no LLM - the same discipline as before. These
answer deterministic questions (does it mention someone, does it trip the
lexicon); whether that *means* something is the detectors' job.
"""

from __future__ import annotations

import html
import re

# The operational lexicon: words that, deterministically, mark a message as
# worth a second look. Not findings - candidates. Matched on word boundaries so
# "helpful" does not trip "help". Shared across every chat provider, because a
# blocker reads the same in Teams as in Slack.
#
# Extended for Teams' operational vocabulary (deploy/rollback/approval/etc.):
# these are the words the Sprint 2 brief named, and they are equally valid
# Slack signals - keeping one lexicon is the point of this module.
LEXICON = (
    "blocked", "blocker", "urgent", "asap", "escalate", "escalation",
    "help", "broken", "outage", "down", "deadline", "critical", "incident",
    "deploy", "deployment", "rollback", "approval", "approve", "regression",
    "hotfix", "postmortem", "sev1", "sev2", "p0", "p1",
)
_LEXICON_RE = re.compile(r"\b(" + "|".join(LEXICON) + r")\b", re.IGNORECASE)

# Slack encodes mentions in message text as tokens, not plain @names:
#   <@U123>            a user      ·  <@W123>        an enterprise user
#   <!here> <!channel> broadcasts  ·  <!subteam^S1|@team>  a user group
_SLACK_USER_RE = re.compile(r"<@([UW][A-Z0-9]+)>")
_SLACK_BROADCAST_RE = re.compile(r"<!(here|channel|everyone)>")
_SLACK_SUBTEAM_RE = re.compile(r"<!subteam\^([A-Z0-9]+)(?:\|[^>]*)?>")

# Teams message bodies are HTML, and a mention is an <at> element whose id
# indexes the message's own `mentions` array. The display name sits inside the
# tag, which is what makes it readable without a directory lookup.
_TEAMS_AT_RE = re.compile(r'<at[^>]*>(.*?)</at>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")

# System messages that are activity but never carry an operational signal - a
# join/leave/topic change is not a mention or a blocker.
SKIP_SUBTYPES = frozenset({
    "channel_join", "channel_leave", "channel_topic", "channel_purpose",
    "channel_name", "channel_archive", "channel_unarchive", "pinned_item",
    "unpinned_item", "bot_add", "bot_remove",
})


def strip_html(text: str | None) -> str:
    """Teams message bodies are HTML; findings quote plain text. Unescapes
    entities too, so `&amp;` reads as `&` in evidence."""
    if not text:
        return ""
    return html.unescape(_TAG_RE.sub(" ", text)).strip()


def match_lexicon(text: str | None) -> list[str]:
    """The operational words a message contains, lowercased and de-duplicated.
    Empty when none - the caller flags a message only when this is non-empty."""
    if not text:
        return []
    return sorted({m.lower() for m in _LEXICON_RE.findall(text)})


def extract_slack_mentions(text: str | None) -> dict | None:
    """Who a Slack message references, or None. Users and group broadcasts are
    kept apart - an `@here` is operationally different from naming a person."""
    if not text:
        return None
    users = _SLACK_USER_RE.findall(text)
    groups = _SLACK_BROADCAST_RE.findall(text) + [f"subteam:{s}" for s in _SLACK_SUBTEAM_RE.findall(text)]
    if not users and not groups:
        return None
    return {"users": users, "groups": groups}


def extract_teams_mentions(body_html: str | None, mentions: list | None = None) -> dict | None:
    """Who a Teams message references, or None.

    Graph gives mentions twice: as `<at>` elements inside the HTML body, and as
    a structured `mentions` array on the message. The array is authoritative
    (it carries the real identity), so it is preferred; the HTML is the fallback
    for the display names alone. A channel-wide mention arrives as a mentioned
    "conversation"/"tag" rather than a user, which is the Teams equivalent of
    Slack's @here broadcast - so it is reported as a group, not a person.
    """
    users: list[str] = []
    groups: list[str] = []
    for m in mentions or []:
        mentioned = (m.get("mentioned") or {}) if isinstance(m, dict) else {}
        if mentioned.get("user"):
            user = mentioned["user"]
            users.append(user.get("id") or user.get("displayName") or "")
        elif mentioned.get("conversation") or mentioned.get("tag"):
            target = mentioned.get("conversation") or mentioned.get("tag") or {}
            groups.append(target.get("displayName") or "channel")
    users = [u for u in users if u]

    if not users and not groups and body_html:
        # No structured array (older messages, or a trimmed $select): fall back
        # to the names rendered in the body.
        names = [strip_html(n) for n in _TEAMS_AT_RE.findall(body_html)]
        users = [n for n in names if n]

    if not users and not groups:
        return None
    return {"users": users, "groups": groups}
