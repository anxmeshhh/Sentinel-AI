"""Meeting History for the Google Meet Workspace - built entirely from the
same Calendar Signal data Calendar itself uses (has_meeting_link=true), not
a separate Meet data source. Google's real meeting-attendance/conference-
record API (actual join times, actual attendee list) is a Workspace-admin-
only API, not available for a personal Google account - so "duration" here
is the *scheduled* duration and "participants" are *invited* attendees, the
best real data actually available, not real call analytics. Status
(upcoming/past/cancelled) is genuinely derivable: cancelled comes straight
from Google's own event.status, upcoming/past from comparing the scheduled
time to now.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.signal import Signal
from app.services.calendar_query import list_calendar_range

MEETING_RANGES = {"upcoming", "past"}


def list_meetings(
    session: Session,
    workspace_id,
    *,
    meeting_range: str,
    search: str | None = None,
    limit: int = 50,
    connection_ids: set[uuid.UUID] | None = None,
) -> list[Signal]:
    """`connection_ids` narrows the read to one Scope's connections - see
    calendar_query's module docstring. A meeting carries its title, attendees
    and a joinable link, so a workspace-wide read is a disclosure."""
    if meeting_range not in MEETING_RANGES:
        raise ValueError(f"unknown meeting range: {meeting_range!r}")

    now = datetime.now(timezone.utc)
    if meeting_range == "upcoming":
        signals = list_calendar_range(
            session, workspace_id, since=now, until=datetime.max, limit=300, connection_ids=connection_ids
        )
    else:
        signals = list_calendar_range(
            session, workspace_id, since=datetime.min, until=now, limit=300, connection_ids=connection_ids
        )
        signals = list(reversed(signals))  # most recent past meeting first

    meetings = [s for s in signals if s.payload.get("has_meeting_link")]
    if search:
        q = search.lower()
        meetings = [s for s in meetings if q in s.payload.get("title", "").lower()]
    return meetings[:limit]


def meeting_status(signal: Signal) -> str:
    if signal.payload.get("status") == "cancelled":
        return "cancelled"
    start = signal.payload.get("start")
    if not start:
        return "past"
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if "T" in start else datetime.fromisoformat(start)
    except ValueError:
        return "past"
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    return "upcoming" if start_dt > datetime.now(timezone.utc) else "past"
