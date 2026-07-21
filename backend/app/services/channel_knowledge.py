"""Channel Knowledge: the authorized documents this channel can reference.

"Knowledge" here is deliberately concrete rather than aspirational: it is the
set of real documents the channel is authorized to see, indexed from the
Drive-file Signals its assigned connections carry, plus the resources an
admin explicitly allow-listed. Nothing is invented, embedded, or summarized
by an LLM - that would be a different (and much larger) feature. This is the
honest version: "here is what this channel knows about, and every item links
to the real thing."

Authorization is the same `_channel_scope` gate everything else uses, and
Drive stays fail-closed: a document appears only if its file id is on the
channel's allow-list. A channel with a Drive connection assigned but nothing
allow-listed has *no* knowledge yet - correctly, since assignment alone
authorizes no specific file.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection import Connection
from app.models.signal import Signal, SignalType
from app.services.channel_briefing import _channel_scope


def build_channel_knowledge(session: Session, team_id: uuid.UUID, *, limit: int = 100) -> dict:
    scope = _channel_scope(session, team_id)
    if not scope["connections"]:
        return {"no_connections": True, "documents": [], "connection_labels": []}

    # Drive-file signals from the channel's assigned connections, newest
    # first. Only files whose id is allow-listed for that connection appear -
    # the fail-closed resource rule, identical to the feed's.
    rows = session.execute(
        select(Signal, Connection)
        .join(Connection, Connection.id == Signal.connection_id)
        .where(
            Signal.connection_id.in_(scope["connections"]),
            Signal.type == SignalType.DRIVE_FILE,
        )
        .order_by(Signal.occurred_at.desc())
        .limit(limit * 2)
    ).all()

    documents = []
    seen: set[str] = set()
    for signal, connection in rows:
        allowed = scope["allowed_resources"].get(connection.id, set())
        if signal.external_id not in allowed:
            continue
        if signal.external_id in seen:
            continue
        seen.add(signal.external_id)
        payload = signal.payload or {}
        documents.append({
            "id": signal.external_id,
            "title": payload.get("title") or payload.get("name") or "Untitled document",
            "url": payload.get("url"),
            "owner": payload.get("owner") or signal.actor,
            "modified_at": signal.occurred_at,
            "source_label": connection.full_name,
        })
        if len(documents) >= limit:
            break

    return {
        "no_connections": False,
        "documents": documents,
        "connection_labels": scope["labels"],
    }
