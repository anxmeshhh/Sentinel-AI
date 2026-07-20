"""Phase 2s: Channel Briefings - the attention loop, scoped to one Channel.

Reuses the existing Attention Engine rather than detecting anything new: a
channel briefing is the workspace's attention list filtered to exactly what
this Channel is authorized to see, plus a short narrative.

## The scoping rules (and why they are what they are)

1. **Connection assignment is a hard gate.** An item is only ever visible in
   a Channel if a Connection for its source provider is actually assigned to
   that Channel (Phase 2l). No assignment, no items - never inferred, never
   widened.

2. **Resource allow-lists are enforced wherever the item has an
   allow-listable resource.** A Drive-sourced item must match an allow-listed
   file/folder if that channel-connection has any allow-list entries.

3. **Email, calendar and PR items are connection-gated only** - deliberately,
   not as a shortcut. Their connections are already 1:1 with their scope in
   this codebase (a GitHub Connection *is* a single repo; a Gmail Connection
   *is* one mailbox), and an email that hasn't arrived yet cannot be
   pre-allow-listed by an admin. This mirrors the orchestrator's existing
   behavior exactly, where `search_emails`/`search_drive` are
   connection-gated and only *reading a specific document* is
   resource-gated. Consistency matters more here than a stricter-looking
   rule that would make email briefings structurally impossible.

Briefings are **read-only**. Done/snooze/dismiss stay in the personal
Attention hub, because an attention item's lifecycle belongs to the person
acting on it - one member marking something done shouldn't silently clear it
from a teammate's view. That question deserves a real answer before a shared
lifecycle is built, not a default.
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.llm import LLMClient, LLMError
from app.models.agent_run import AgentRun
from app.models.attention_item import AttentionItem, AttentionType
from app.models.channel_connection import ChannelConnection, ChannelConnectionResource
from app.models.connection import Connection, Provider
from app.models.finding import Finding
from app.services.attention_engine import list_attention

logger = structlog.get_logger("sentinel.channel_briefing")

# Which provider backs each attention type. `FINDING` is absent on purpose -
# findings are attributed through their agent run's connection instead (an
# agent isn't a Connection), and MANUAL items have no provider at all.
TYPE_PROVIDERS: dict[AttentionType, Provider] = {
    AttentionType.IMPORTANT_EMAIL: Provider.GMAIL,
    AttentionType.UPCOMING_MEETING: Provider.GOOGLE_CALENDAR,
    AttentionType.STALE_PR: Provider.GITHUB,
}

# Item types whose dedupe key points at a resource an admin could plausibly
# allow-list. Drive-backed items (deadlines extracted from documents, Phase
# 2t) are the real case; see rule 3 in the module docstring for why email /
# calendar / PR items are not in here.
RESOURCE_SCOPED_PREFIXES = ("drive:", "deadline:")


def build_channel_briefing(session: Session, team_id: uuid.UUID, workspace_id: uuid.UUID) -> dict:
    scope = _channel_scope(session, team_id)
    if not scope["connections"]:
        return {
            "items": [],
            "narrative": None,
            "connection_labels": [],
            "no_connections": True,
        }

    all_items = list_attention(session, workspace_id)
    visible = [i for i in all_items if _is_visible_in_channel(session, i, scope)]

    return {
        "items": visible,
        "narrative": _narrate(visible, scope["labels"]),
        "connection_labels": scope["labels"],
        "no_connections": False,
    }


def _channel_scope(session: Session, team_id: uuid.UUID) -> dict:
    """Everything this Channel is authorized for, resolved once per request."""
    rows = session.execute(
        select(ChannelConnection, Connection)
        .join(Connection, Connection.id == ChannelConnection.connection_id)
        .where(ChannelConnection.team_id == team_id)
    ).all()

    providers: set[Provider] = set()
    connection_ids: set[uuid.UUID] = set()
    labels: list[str] = []
    allowed_resources: dict[uuid.UUID, set[str]] = {}

    for channel_connection, connection in rows:
        providers.add(connection.provider)
        connection_ids.add(connection.id)
        labels.append(f"{connection.provider.value}:{connection.full_name}")
        keys = set(
            session.execute(
                select(ChannelConnectionResource.resource_key).where(
                    ChannelConnectionResource.channel_connection_id == channel_connection.id
                )
            ).scalars()
        )
        if keys:
            allowed_resources[connection.id] = keys

    return {
        "connections": connection_ids,
        "providers": providers,
        "labels": labels,
        "allowed_resources": allowed_resources,
    }


def _is_visible_in_channel(session: Session, item: AttentionItem, scope: dict) -> bool:
    # Manual reminders are personal by definition - they belong to whoever
    # created them, not to a shared channel view.
    if item.type == AttentionType.MANUAL:
        return False

    if item.type == AttentionType.FINDING:
        return _finding_connection_is_assigned(session, item, scope)

    provider = TYPE_PROVIDERS.get(item.type)
    if provider is None or provider not in scope["providers"]:
        return False

    if item.dedupe_key.startswith(RESOURCE_SCOPED_PREFIXES):
        return _resource_is_allowed(item, scope)
    return True


def _resource_is_allowed(item: AttentionItem, scope: dict) -> bool:
    """Fail-closed for resource-scoped items: if the channel has configured
    an allow-list for the backing connection, the item's resource must be on
    it. A resource-scoped item with no allow-list anywhere stays hidden -
    the admin hasn't authorized any documents for this channel yet."""
    resource_key = item.dedupe_key.split(":", 1)[1] if ":" in item.dedupe_key else item.dedupe_key
    for allowed in scope["allowed_resources"].values():
        if resource_key in allowed:
            return True
    return False


def _finding_connection_is_assigned(session: Session, item: AttentionItem, scope: dict) -> bool:
    """A finding is an agent's opinion about one connection's data - visible
    in a channel only if that same connection is assigned to it."""
    try:
        finding_id = uuid.UUID(item.dedupe_key.split(":", 1)[1])
    except (IndexError, ValueError):
        return False

    connection_id = session.execute(
        select(AgentRun.connection_id).join(Finding, Finding.run_id == AgentRun.id).where(Finding.id == finding_id)
    ).scalar_one_or_none()
    return connection_id is not None and connection_id in scope["connections"]


def _narrate(items: list[AttentionItem], labels: list[str]) -> str | None:
    if not items:
        return None

    facts = {
        "total": len(items),
        "by_type": {t.value: sum(1 for i in items if i.type == t) for t in {i.type for i in items}},
        "top_titles": [i.title for i in items[:3]],
        "connections": labels,
        "soonest_due": next((i.due_at.isoformat() for i in items if i.due_at), None),
    }

    try:
        result = LLMClient().complete_json(
            system=(
                "You are Sentinel, briefing a team channel. Summarize what needs the channel's attention. "
                "STRICT RULES: maximum 3 short sentences; only use facts present in the data - never invent "
                "specifics; plain text, no markdown, no greetings; lead with the most time-sensitive item. "
                'Return JSON: {"narrative": "..."}'
            ),
            user=f"Channel attention data: {facts}",
        )
        narrative = (result.get("narrative") or "").strip()
        if narrative:
            return narrative
    except LLMError:
        logger.warning("channel_briefing_llm_unavailable_using_fallback")

    # Deterministic fallback - the briefing degrades in charm, never in
    # correctness (same discipline as Catch Me Up).
    parts = [f"{count} {label.replace('_', ' ')}" for label, count in facts["by_type"].items()]
    return f"{facts['total']} items need this channel's attention: " + ", ".join(parts) + "."


def channel_pending_count(session: Session, team_id: uuid.UUID, workspace_id: uuid.UUID) -> int:
    """Cheap count for the channel header chip - same scoping, no narration
    (so it never spends an LLM call)."""
    scope = _channel_scope(session, team_id)
    if not scope["connections"]:
        return 0
    return sum(1 for i in list_attention(session, workspace_id) if _is_visible_in_channel(session, i, scope))
