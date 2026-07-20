"""Phase 2v: deterministic "is this actually for me?" signals.

Motivation, from real data: the attention feed was surfacing roughly one
genuinely actionable item out of six. The rest were job alerts and event
marketing.

## What measurement changed

These rules were tuned against a real inbox (259 messages / 33 flagged),
not designed on intuition, and two confident hypotheses died on contact:

- **`List-Unsubscribe` was supposed to be the headline signal** - the 2024
  Gmail/Yahoo bulk-sender rules make it near-mandatory, so it "should" flag
  almost all mass mail. Measured: present on **1 of 33**. Kept, because it's
  free and correct when present, but it carries almost none of the weight.
- **"Is the user in To:?" was supposed to separate personal from blast.**
  Measured: `True` for **every single message**, bulk included. Removed
  entirely rather than shipped as dead weight.

What actually discriminates, in order of measured value:

1. **Repetition** - the same sender appearing 3+ times in the window. A
   person does not send you the same thing five times a week; a job board
   does. (Measured: 5x abekus, 4x codebenders, 4x unstop, 3x jobrapido.)
2. **Automated local-part** - `noreply@`, `alert@`, `mailer-daemon@`.
   Caught ~45% on its own.
3. **`List-Unsubscribe`** - rare here, but unambiguous when set.

A **bulk sending-subdomain** rule (`emails.`, `info.`, `content.`) was
built, measured, and **deliberately dropped**: it cut 33 down to 3, but
among the casualties was "your domain has expired" - the most actionable
message in the inbox. Fewer items is not the goal; the right items is.

Everything here is a pure function over metadata already stored. No LLM, no
network, no per-message cost.
"""

import re

# Local-parts that mean "a machine sent this and nobody is reading replies".
# Deliberately matched as whole tokens against the local-part rather than as
# substrings anywhere in the address, so a real person at
# "alerting-systems.com" isn't misclassified.
AUTOMATED_LOCAL_PARTS = {
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply", "do_not_reply",
    "notification", "notifications", "notify", "alert", "alerts", "alerting",
    "mailer", "mail", "mailer-daemon", "bounce", "bounces", "postmaster",
    "automated", "autoreply", "auto-reply", "system", "daemon", "robot", "bot",
    "newsletter", "news", "updates", "info", "marketing", "promo", "promotions",
    "support-noreply", "team-noreply",
}

# Split on the separators bulk senders use to build addresses like
# "messages-noreply@linkedin.com" or "jobs.alert@example.com", so the token
# check catches them.
_LOCAL_TOKEN_RE = re.compile(r"[.\-_+]")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def extract_address(raw_from: str | None) -> str | None:
    """Pull the bare address out of a `"Name" <a@b.com>` header value."""
    if not raw_from:
        return None
    match = _EMAIL_RE.search(raw_from)
    return match.group(0).lower() if match else None


def is_automated_sender(raw_from: str | None) -> bool:
    address = extract_address(raw_from)
    if address is None:
        return False
    local_part = address.split("@", 1)[0]
    tokens = set(_LOCAL_TOKEN_RE.split(local_part))
    tokens.add(local_part)
    return bool(tokens & AUTOMATED_LOCAL_PARTS)


REPETITION_THRESHOLD = 3  # same sender this many times in the window = a feed, not a person

# Rescue valve for the repetition rule, added because measurement caught it
# discarding a real "Interview Invite from Planys Technologies" - the sender
# was a job board that had sent 9 messages that week, so volume alone
# condemned a message that genuinely mattered.
#
# Deliberately narrow: each phrase names a specific commitment or
# transaction, not general enthusiasm. Marketing subjects like "Immediate
# Hiring - Apply Now!" or "Last Chance to Book" match none of them. This
# rescues from *repetition only* - a true mailing-list blast still stays
# filtered, because volume isn't the reason we distrust those.
HIGH_SIGNAL_PHRASES = (
    "interview invite", "interview invitation", "interview scheduled", "interview confirmed",
    "offer letter", "job offer",
    "invoice", "payment failed", "payment due", "payment overdue", "receipt for",
    "contract", "agreement", "signature requested", "signed",
    "has expired", "expiring soon", "renewal required",
    "action required", "final notice",
)


def has_high_signal_subject(payload: dict) -> bool:
    subject = (payload.get("subject") or "").lower()
    return any(phrase in subject for phrase in HIGH_SIGNAL_PHRASES)


def looks_like_bulk(payload: dict) -> bool:
    """Per-message bulk signals: an unsubscribe header, or a sender whose
    address announces that nobody reads replies.

    `is_bulk` comes from the List-Unsubscribe header (see gmail_client.py).
    Messages ingested before Phase 2v lack the key entirely, so its absence
    means "unknown" and falls through to the sender heuristic - old rows
    degrade to prior behavior rather than being silently reclassified.
    """
    if payload.get("is_bulk"):
        return True
    return is_automated_sender(payload.get("from"))


def sender_counts(payloads: list[dict]) -> dict[str, int]:
    """How often each sender appears across the window. Needs the whole set,
    which is why it lives here rather than in a per-message check."""
    counts: dict[str, int] = {}
    for payload in payloads:
        address = extract_address(payload.get("from"))
        if address:
            counts[address] = counts.get(address, 0) + 1
    return counts


def noise_reason(payload: dict, counts: dict[str, int]) -> str | None:
    """Why this message is being kept out of the attention feed, or None if
    it isn't. Returning the reason (rather than a bare bool) is what lets
    the ranking be explained instead of just trusted."""
    address = extract_address(payload.get("from"))
    if address and counts.get(address, 0) >= REPETITION_THRESHOLD and not has_high_signal_subject(payload):
        return f"{counts[address]} messages from this sender this week"
    if payload.get("is_bulk"):
        return "bulk mailing list"
    if is_automated_sender(payload.get("from")):
        return "automated sender"
    return None


def describe_signals(payload: dict, counts: dict[str, int] | None = None) -> dict:
    """Everything measured about a message's "is this for me" character -
    used by the detector and by the script that tuned these thresholds."""
    counts = counts or {}
    return {
        "has_unsubscribe": bool(payload.get("is_bulk")),
        "automated_sender": is_automated_sender(payload.get("from")),
        "sender_count": counts.get(extract_address(payload.get("from")) or "", 0),
        "noise_reason": noise_reason(payload, counts),
    }
