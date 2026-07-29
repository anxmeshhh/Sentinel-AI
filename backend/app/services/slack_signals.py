"""Deterministic extraction of operational signals from Slack messages.

Pure functions, no network and no LLM - the Phase 2 discipline. Given a
message's text, they answer two deterministic questions: does it mention someone,
and does it trip the operational lexicon. The *meaning* (is this really a
blocker, is a question unanswered) is Phase 3's job, on top of these facts.

Kept small and testable on purpose: the exact lexicon and mention grammar are
the things most likely to be tuned against real data, so they live in one place
with their own tests rather than buried in the ingestion loop.
"""

import re

# Slack encodes mentions in message text as tokens, not plain @names:
#   <@U123>            a user      ·  <@W123>        an enterprise user
#   <!here> <!channel> broadcasts  ·  <!subteam^S1|@team>  a user group
_USER_RE = re.compile(r"<@([UW][A-Z0-9]+)>")
_BROADCAST_RE = re.compile(r"<!(here|channel|everyone)>")
_SUBTEAM_RE = re.compile(r"<!subteam\^([A-Z0-9]+)(?:\|[^>]*)?>")

# The operational lexicon: words that, deterministically, mark a message as
# worth a second look. Not findings - candidates. Matched on word boundaries so
# "helpful" does not trip "help". Deliberately small; it is the thing Phase 4
# measurement will tune against real traffic.
LEXICON = (
    "blocked", "blocker", "urgent", "asap", "escalate", "escalation",
    "help", "broken", "outage", "down", "deadline", "critical", "incident",
)
_LEXICON_RE = re.compile(r"\b(" + "|".join(LEXICON) + r")\b", re.IGNORECASE)

# System messages that are activity but never carry an operational signal - a
# join/leave/topic change is not a mention or a blocker.
SKIP_SUBTYPES = frozenset({
    "channel_join", "channel_leave", "channel_topic", "channel_purpose",
    "channel_name", "channel_archive", "channel_unarchive", "pinned_item",
    "unpinned_item", "bot_add", "bot_remove",
})


def extract_mentions(text: str | None) -> dict | None:
    """Who a message references, or None. Returns user ids and group tokens
    separately - a `@here` broadcast is operationally different from naming a
    person, and later logic may weigh them differently."""
    if not text:
        return None
    users = _USER_RE.findall(text)
    groups = _BROADCAST_RE.findall(text) + [f"subteam:{s}" for s in _SUBTEAM_RE.findall(text)]
    if not users and not groups:
        return None
    return {"users": users, "groups": groups}


def match_lexicon(text: str | None) -> list[str]:
    """The operational words a message contains, lowercased and de-duplicated.
    Empty when none - the caller flags a message only when this is non-empty."""
    if not text:
        return []
    return sorted({m.lower() for m in _LEXICON_RE.findall(text)})
