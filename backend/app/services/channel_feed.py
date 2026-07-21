"""Phase 2y: the Channel Feed.

Normalized updates from the connections this Channel is authorized for, in
time order. It is the raw "what happened" layer underneath Attention's "what
needs a decision" layer, and it is deliberately thin - a projection of
existing Signals, not a new pipeline.

## Scoping is the whole implementation

The feed reads `_channel_scope` from `channel_briefing` rather than
re-deriving which connections a channel may see. That function is already
the single answer to "what is this channel authorized for", and a second
implementation of it here would be a second place for that rule to be wrong.

Drive-sourced items stay resource-gated for the same reason they are in
briefings: one Drive connection covers many documents, so assignment alone
authorizes none of them.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection import Connection
from app.models.signal import Signal, SignalType
from app.services.channel_briefing import RESOURCE_SCOPED_PROVIDERS, _channel_scope

# What each signal type is called in the feed. Kept explicit rather than
# prettifying the enum name, so the wording is a product decision instead of
# a string transformation.
TYPE_LABELS: dict[SignalType, str] = {
    SignalType.PR: "Pull request",
    SignalType.REVIEW_SUBMITTED: "Review",
    SignalType.COMMIT: "Commit",
    SignalType.ISSUE: "Issue",
    SignalType.CALENDAR_EVENT: "Meeting",
    SignalType.EMAIL: "Email",
    SignalType.DRIVE_FILE: "Document",
}


def build_channel_feed(session: Session, team_id: uuid.UUID, limit: int = 50) -> dict:
    scope = _channel_scope(session, team_id)
    if not scope["connections"]:
        return {"items": [], "no_connections": True, "connection_labels": []}

    rows = session.execute(
        select(Signal, Connection)
        .join(Connection, Connection.id == Signal.connection_id)
        .where(Signal.connection_id.in_(scope["connections"]))
        .order_by(Signal.occurred_at.desc())
        .limit(limit * 2)  # over-fetch: resource gating below may drop some
    ).all()

    items = []
    for signal, connection in rows:
        if connection.provider in RESOURCE_SCOPED_PROVIDERS and not _resource_allowed(signal, connection, scope):
            continue
        items.append(_to_item(signal, connection))
        if len(items) >= limit:
            break

    return {"items": items, "no_connections": False, "connection_labels": scope["labels"]}


def _resource_allowed(signal: Signal, connection: Connection, scope: dict) -> bool:
    allowed = scope["allowed_resources"].get(connection.id)
    if not allowed:
        return False  # fail closed: nothing allow-listed means nothing visible
    return signal.external_id in allowed


def _to_item(signal: Signal, connection: Connection) -> dict:
    payload = signal.payload or {}
    title = payload.get("title") or payload.get("subject") or signal.external_id
    return {
        "id": signal.id,
        "type": signal.type.value,
        "type_label": TYPE_LABELS.get(signal.type, signal.type.value),
        "title": title,
        "actor": signal.actor,
        "provider": connection.provider.value,
        "source_label": connection.full_name,
        "url": payload.get("url"),
        "occurred_at": signal.occurred_at,
    }


def channel_feed_since(session: Session, team_id: uuid.UUID, since: datetime, limit: int = 50) -> dict:
    """Same feed, filtered to what arrived after `since`.

    Exists so the client can poll for new activity without re-rendering the
    whole list - the modules have to stay live as connections keep syncing.
    """
    result = build_channel_feed(session, team_id, limit=limit)
    result["items"] = [i for i in result["items"] if i["occurred_at"] > since]
    return result
