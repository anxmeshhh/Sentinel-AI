"""Structured Calendar browsing - same philosophy as mail_query.py: a small
fixed set of predictable views, no open-ended query engine.

## Whose calendar

Every read here takes a `connection_ids` set - the Scope's connections - and
returns events only from those. A calendar event belongs to whoever connected
the account it came from, so a workspace-wide read would hand one member's
meeting titles, attendees and links to another. Personal reads pass the
caller's own connections; a channel passes what it is authorized for.

`free_slots_for_availability` is the one deliberate exception, and the reason
it is safe is its return type: it answers "is this time free?" with times and
nothing else. Combining a private calendar with a shared one to find a slot
is exactly what Sentinel should do; disclosing what occupies the slot is not.
So the wider read exists in one function whose shape cannot leak a title.
"""

import uuid
from datetime import date as date_cls
from datetime import datetime, time, timezone

from sqlalchemy.orm import Session

from app.models.signal import Signal
from app.repositories.signals import SignalRepository

CALENDAR_RANGES = {"upcoming", "past"}


def list_calendar(
    session: Session,
    workspace_id,
    *,
    calendar_range: str,
    limit: int = 30,
    connection_ids: set[uuid.UUID] | None = None,
) -> list[Signal]:
    repo = SignalRepository(session, workspace_id)
    now = datetime.now(timezone.utc)

    if calendar_range == "upcoming":
        return repo.list_calendar(since=now, ascending=True, limit=limit, connection_ids=connection_ids)
    if calendar_range == "past":
        return repo.list_calendar(until=now, ascending=False, limit=limit, connection_ids=connection_ids)

    raise ValueError(f"unknown calendar range: {calendar_range!r}")


def list_calendar_range(
    session: Session,
    workspace_id,
    *,
    since: datetime,
    until: datetime,
    limit: int = 50,
    connection_ids: set[uuid.UUID] | None = None,
) -> list[Signal]:
    """Explicit date-range query - used by the AI Command orchestrator for
    requests like "meetings this week" or "anything at 3pm today", which
    don't fit the simple upcoming/past split above.
    """
    repo = SignalRepository(session, workspace_id)
    return repo.list_calendar(
        since=since, until=until, ascending=True, limit=limit, connection_ids=connection_ids
    )


def list_calendar_month(
    session: Session, workspace_id, *, year: int, month: int, connection_ids: set[uuid.UUID] | None = None
) -> list[Signal]:
    """Every event in one calendar month - backs the Month grid view."""
    since = datetime(year, month, 1, tzinfo=timezone.utc)
    until = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return list_calendar_range(
        session, workspace_id, since=since, until=until, limit=300, connection_ids=connection_ids
    )


def find_free_slots(
    session: Session,
    workspace_id,
    *,
    date: str,
    start_hour: int = 9,
    end_hour: int = 18,
    duration_minutes: int = 30,
    connection_ids: set[uuid.UUID] | None = None,
) -> list[dict]:
    """Deterministic gap-finding between existing events on one day - the
    orchestrator's find_free_slot tool narrates this, it doesn't compute it.
    Same discipline as every other agent: real evidence first, LLM after.
    """
    day = date_cls.fromisoformat(date)
    window_start = datetime.combine(day, time(hour=start_hour), tzinfo=timezone.utc)
    window_end = datetime.combine(day, time(hour=end_hour), tzinfo=timezone.utc)
    if window_end <= window_start:
        return []

    events = list_calendar_range(
        session, workspace_id, since=window_start, until=window_end, limit=50, connection_ids=connection_ids
    )
    spans = sorted(s for s in (_event_span(e, window_start, window_end) for e in events) if s)

    gaps: list[dict] = []
    cursor = window_start
    for start, end in spans:
        if start > cursor:
            _maybe_add_gap(gaps, cursor, start, duration_minutes)
        cursor = max(cursor, end)
    if window_end > cursor:
        _maybe_add_gap(gaps, cursor, window_end, duration_minutes)

    return gaps


def free_slots_for_availability(
    session: Session,
    workspace_id,
    *,
    date: str,
    connection_ids: set[uuid.UUID],
    start_hour: int = 9,
    end_hour: int = 18,
    duration_minutes: int = 30,
) -> list[dict]:
    """Availability across several calendars, WITHOUT disclosing any of them.

    This is the "combine, never expose" rule made structural. It reads the
    union of connections it is given - which may include a member's personal
    calendar alongside a shared team one - and returns only
    ``{start, end, minutes}``. There is no title, no attendee, no organiser
    and no owner in the result, so "3 PM is unavailable" is the most it can
    ever say. It physically cannot report *whose* appointment that is.

    Deliberately a separate function from `find_free_slots` rather than a
    flag on it: the wider read is the dangerous one, so it lives somewhere
    named for what makes it safe.
    """
    return find_free_slots(
        session,
        workspace_id,
        date=date,
        start_hour=start_hour,
        end_hour=end_hour,
        duration_minutes=duration_minutes,
        connection_ids=connection_ids,
    )


def _event_span(signal: Signal, window_start: datetime, window_end: datetime) -> tuple[datetime, datetime] | None:
    start_raw = signal.payload.get("start")
    end_raw = signal.payload.get("end")
    if not start_raw or not end_raw:
        return None
    try:
        start = _parse_ts(start_raw)
        end = _parse_ts(end_raw)
    except ValueError:
        return None
    start, end = max(start, window_start), min(end, window_end)
    return (start, end) if end > start else None


def _parse_ts(value: str) -> datetime:
    if "T" not in value:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _maybe_add_gap(gaps: list[dict], start: datetime, end: datetime, min_minutes: int) -> None:
    minutes = (end - start).total_seconds() / 60
    if minutes >= min_minutes:
        gaps.append({"start": start.isoformat(), "end": end.isoformat(), "minutes": round(minutes)})


def calendar_summary_for_assistant(
    session: Session, workspace_id, limit: int = 5, connection_ids: set[uuid.UUID] | None = None
) -> str:
    """The Assistant's calendar context. Scoped like every other read here -
    an assistant answering for one person must not be handed another's
    meetings as background."""
    upcoming = list_calendar(
        session, workspace_id, calendar_range="upcoming", limit=limit, connection_ids=connection_ids
    )
    lines = ["Upcoming calendar events:" if upcoming else "No upcoming calendar events."]
    for s in upcoming:
        lines.append(
            f"- \"{s.payload.get('title', '(no title)')}\" at {s.payload.get('start')} "
            f"({s.payload.get('attendee_count', 0)} attendees)"
        )
    return "\n".join(lines)
