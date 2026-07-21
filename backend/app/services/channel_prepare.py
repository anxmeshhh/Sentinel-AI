"""Channel Prepare Me: upcoming meetings this channel is authorized to see,
each preparable into a brief.

The heavy lifting already exists - `meeting_prep.prepare_meeting()` builds a
grounded brief and is already `team_id`-aware, so a brief requested inside a
channel can only read that channel's authorized connections. This module is
just the channel-scoped *list* of what's preparable: upcoming CALENDAR_EVENT
signals from the channel's assigned calendar connection.

Scoping is the same `_channel_scope` gate as everything else. A channel with
no calendar connection assigned has nothing to prepare - correctly.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection import Connection
from app.models.signal import Signal, SignalType
from app.services.channel_briefing import _channel_scope


def list_upcoming_meetings(session: Session, team_id: uuid.UUID, *, limit: int = 20) -> dict:
    scope = _channel_scope(session, team_id)
    if not scope["connections"]:
        return {"no_connections": True, "meetings": []}

    now = datetime.now(timezone.utc)
    rows = session.execute(
        select(Signal)
        .where(
            Signal.connection_id.in_(scope["connections"]),
            Signal.type == SignalType.CALENDAR_EVENT,
            Signal.occurred_at >= now,
        )
        .order_by(Signal.occurred_at.asc())
        .limit(limit)
    ).scalars().all()

    meetings = []
    for signal in rows:
        payload = signal.payload or {}
        if payload.get("status") == "cancelled":
            continue
        meetings.append({
            "signal_id": signal.id,
            "external_id": signal.external_id,
            "title": payload.get("title") or "Untitled meeting",
            "start": payload.get("start"),
            "attendee_count": payload.get("attendee_count") or len(payload.get("attendee_emails") or []),
            "url": payload.get("url"),
        })

    return {"no_connections": False, "meetings": meetings}
