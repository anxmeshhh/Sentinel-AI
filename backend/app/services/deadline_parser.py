"""Phase 2t: deterministic deadline extraction.

No LLM. Deadlines are detected by pattern, for three reasons that all point
the same way:

- **Precision.** A hallucinated deadline is worse than a missed one - it
  sends someone chasing a commitment that doesn't exist. Patterns are
  auditable; a model's guess is not.
- **Cost.** This runs over every email subject on every sync. An LLM call
  per subject would exhaust the free-tier token budget within minutes.
- **What's actually available.** Email bodies are never stored (a
  deliberate privacy property of this codebase - see gmail_client.py), so
  detection reads subjects, plus document text only where it already exists.

The precision rule that does the real work: **a date alone is never a
deadline.** "Meeting on Friday" is not a commitment; "Reply by Friday" is.
A deadline keyword must be present, so the parser stays quiet on the
enormous volume of ordinary dated text.

Deliberately unsupported: bare numeric dates like `11/12`. There is no way
to tell 11 December from November 12 without knowing the writer's locale,
and guessing wrong produces a confidently incorrect deadline - exactly the
failure this module exists to avoid.
"""

import re
from datetime import date, datetime, time, timedelta, timezone

# Words that turn a date into a commitment. Kept broad across professions
# (invoices, coursework, contracts, submissions) rather than assuming any
# one kind of work.
_KEYWORDS = (
    r"due|deadline|expires?|expiring|expiry|last day|closes?|closing|"
    r"submit by|submission|respond by|reply by|rsvp by|renew|renewal|"
    r"payment required|final call|ends?\s+on|cut[- ]?off"
)
KEYWORD_RE = re.compile(_KEYWORDS, re.IGNORECASE)

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_ISO_RE = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
_DAY_MONTH_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(_MONTHS) + r")\b", re.IGNORECASE)
_MONTH_DAY_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.IGNORECASE)
_IN_N_RE = re.compile(r"\bin\s+(\d{1,3})\s+(day|days|week|weeks|hour|hours)\b", re.IGNORECASE)
_WEEKDAY_RE = re.compile(r"\b(?:by|before|on|until|till)\s+(" + "|".join(_WEEKDAYS) + r")\b", re.IGNORECASE)
_RELATIVE_WORD_RE = re.compile(r"\b(today|tomorrow|tonight)\b", re.IGNORECASE)

MAX_HORIZON_DAYS = 120  # beyond this it isn't actionable attention, it's a calendar entry


def find_deadline(text: str, *, now: datetime) -> datetime | None:
    """Return the deadline `text` commits to, or None.

    Requires a deadline keyword AND a resolvable date. Past dates and dates
    beyond the horizon return None - both are real, but neither is something
    to act on today.
    """
    if not text or not KEYWORD_RE.search(text):
        return None

    parsed = _parse_date(text, now=now)
    if parsed is None:
        return None

    # End-of-day: "due 30 November" means the whole of the 30th, not 00:00.
    deadline = parsed if isinstance(parsed, datetime) else datetime.combine(parsed, time(17, 0), tzinfo=timezone.utc)

    if deadline < now - timedelta(hours=12):  # small grace so "due today" survives the working day
        return None
    if deadline > now + timedelta(days=MAX_HORIZON_DAYS):
        return None
    return deadline


def _parse_date(text: str, *, now: datetime) -> date | datetime | None:
    if match := _ISO_RE.search(text):
        year, month, day = (int(g) for g in match.groups())
        return _safe_date(year, month, day)

    if match := _IN_N_RE.search(text):
        amount, unit = int(match.group(1)), match.group(2).lower()
        if unit.startswith("hour"):
            return now + timedelta(hours=amount)
        delta = timedelta(weeks=amount) if unit.startswith("week") else timedelta(days=amount)
        return (now + delta).date()

    if match := _RELATIVE_WORD_RE.search(text):
        word = match.group(1).lower()
        return now.date() if word in ("today", "tonight") else now.date() + timedelta(days=1)

    if match := _DAY_MONTH_RE.search(text):
        day, month = int(match.group(1)), _MONTHS[match.group(2).lower()]
        return _with_inferred_year(month, day, now)

    if match := _MONTH_DAY_RE.search(text):
        month, day = _MONTHS[match.group(1).lower()], int(match.group(2))
        return _with_inferred_year(month, day, now)

    if match := _WEEKDAY_RE.search(text):
        target = _WEEKDAYS[match.group(1).lower()]
        ahead = (target - now.weekday()) % 7
        return now.date() + timedelta(days=ahead or 7)  # "by Monday" on a Monday means next Monday

    return None


def _with_inferred_year(month: int, day: int, now: datetime) -> date | None:
    """A bare "30 November" means the next 30 November. Without this,
    every December message about January would resolve to the past and be
    silently dropped."""
    candidate = _safe_date(now.year, month, day)
    if candidate is None:
        return None
    if candidate < now.date() - timedelta(days=1):
        return _safe_date(now.year + 1, month, day)
    return candidate


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:  # e.g. "31 February" in marketing copy
        return None
