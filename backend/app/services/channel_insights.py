"""Channel Insights: operational intelligence, computed - not narrated.

Every number here is a deterministic aggregation over the Signals this
channel is *authorized* to see (the same `_channel_scope` gate the Feed and
Briefing use), so Insights can never surface data from a connection the
channel wasn't given. No LLM: the same discipline as the Attention Engine -
facts are computed in Python, and the only "intelligence" is choosing which
facts are worth showing. A stat you can't trace back to a real signal has no
place on this page.

Scope: the last N days (default 30), because "operational intelligence"
about a team is about its recent cadence, not its whole history - and an
unbounded window would make the busiest workspace the slowest page.
"""

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection import Connection
from app.models.signal import Signal, SignalType
from app.services.channel_briefing import RESOURCE_SCOPED_PROVIDERS, _channel_scope

# Which signal types count as which kind of activity, for the headline
# tiles. Kept explicit so the wording is a product decision, not a mechanical
# enum split.
_ACTIVITY_LABEL = {
    SignalType.EMAIL: "Emails",
    SignalType.CALENDAR_EVENT: "Meetings",
    SignalType.PR: "Pull requests",
    SignalType.REVIEW_SUBMITTED: "Reviews",
    SignalType.COMMIT: "Commits",
    SignalType.ISSUE: "Issues",
    SignalType.DRIVE_FILE: "Documents",
}


def build_channel_insights(session: Session, team_id: uuid.UUID, *, days: int = 30) -> dict:
    scope = _channel_scope(session, team_id)
    if not scope["connections"]:
        return {"no_connections": True, "window_days": days, "total": 0, "by_type": [], "top_actors": [], "busiest_day": None}

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = session.execute(
        select(Signal, Connection)
        .join(Connection, Connection.id == Signal.connection_id)
        .where(Signal.connection_id.in_(scope["connections"]), Signal.occurred_at >= since)
    ).all()

    # Resource-gated providers (Drive) only count signals actually
    # allow-listed - the same fail-closed rule the feed applies, so a count
    # can never include a document the channel isn't authorized for.
    visible = [
        s for s, c in rows
        if c.provider not in RESOURCE_SCOPED_PROVIDERS
        or s.external_id in scope["allowed_resources"].get(c.id, set())
    ]

    by_type = Counter(s.type for s in visible)
    actors = Counter(s.actor for s in visible if s.actor)
    by_day = Counter(s.occurred_at.date().isoformat() for s in visible)

    busiest = max(by_day.items(), key=lambda kv: kv[1]) if by_day else None

    return {
        "no_connections": False,
        "window_days": days,
        "total": len(visible),
        "connection_labels": scope["labels"],
        "by_type": [
            {"type": t.value, "label": _ACTIVITY_LABEL.get(t, t.value), "count": n}
            for t, n in by_type.most_common()
        ],
        "top_actors": [{"actor": a, "count": n} for a, n in actors.most_common(6)],
        "busiest_day": {"date": busiest[0], "count": busiest[1]} if busiest else None,
    }
