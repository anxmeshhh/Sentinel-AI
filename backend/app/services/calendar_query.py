"""Structured Calendar browsing - same philosophy as mail_query.py: a small
fixed set of predictable views, no open-ended query engine.
"""

from datetime import date as date_cls
from datetime import datetime, time, timezone

from sqlalchemy.orm import Session

from app.models.signal import Signal
from app.repositories.signals import SignalRepository

CALENDAR_RANGES = {"upcoming", "past"}


def list_calendar(session: Session, workspace_id, *, calendar_range: str, limit: int = 30) -> list[Signal]:
    repo = SignalRepository(session, workspace_id)
    now = datetime.now(timezone.utc)

    if calendar_range == "upcoming":
        return repo.list_calendar(since=now, ascending=True, limit=limit)
    if calendar_range == "past":
        return repo.list_calendar(until=now, ascending=False, limit=limit)

    raise ValueError(f"unknown calendar range: {calendar_range!r}")


def list_calendar_range(session: Session, workspace_id, *, since: datetime, until: datetime, limit: int = 50) -> list[Signal]:
    """Explicit date-range query - used by the AI Command orchestrator for
    requests like "meetings this week" or "anything at 3pm today", which
    don't fit the simple upcoming/past split above.
    """
    repo = SignalRepository(session, workspace_id)
    return repo.list_calendar(since=since, until=until, ascending=True, limit=limit)


def list_calendar_month(session: Session, workspace_id, *, year: int, month: int) -> list[Signal]:
    """Every event in one calendar month - backs the Month grid view."""
    since = datetime(year, month, 1, tzinfo=timezone.utc)
    until = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return list_calendar_range(session, workspace_id, since=since, until=until, limit=300)


def find_free_slots(
    session: Session,
    workspace_id,
    *,
    date: str,
    start_hour: int = 9,
    end_hour: int = 18,
    duration_minutes: int = 30,
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

    events = list_calendar_range(session, workspace_id, since=window_start, until=window_end, limit=50)
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


def calendar_summary_for_assistant(session: Session, workspace_id, limit: int = 5) -> str:
    upcoming = list_calendar(session, workspace_id, calendar_range="upcoming", limit=limit)
    lines = ["Upcoming calendar events:" if upcoming else "No upcoming calendar events."]
    for s in upcoming:
        lines.append(
            f"- \"{s.payload.get('title', '(no title)')}\" at {s.payload.get('start')} "
            f"({s.payload.get('attendee_count', 0)} attendees)"
        )
    return "\n".join(lines)
