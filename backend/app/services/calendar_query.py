"""Structured Calendar browsing - same philosophy as mail_query.py: a small
fixed set of predictable views, no open-ended query engine.
"""

from datetime import datetime, timezone

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


def calendar_summary_for_assistant(session: Session, workspace_id, limit: int = 5) -> str:
    upcoming = list_calendar(session, workspace_id, calendar_range="upcoming", limit=limit)
    lines = ["Upcoming calendar events:" if upcoming else "No upcoming calendar events."]
    for s in upcoming:
        lines.append(
            f"- \"{s.payload.get('title', '(no title)')}\" at {s.payload.get('start')} "
            f"({s.payload.get('attendee_count', 0)} attendees)"
        )
    return "\n".join(lines)
