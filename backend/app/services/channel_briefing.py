"""Phase 2s: Channel Briefings - the attention loop, scoped to one Channel.

Reuses the existing Attention Engine rather than detecting anything new: a
channel briefing is the workspace's attention list filtered to exactly what
this Channel is authorized to see, plus a short narrative.

## The scoping rules (and why they are what they are)

1. **The item's own connection is a hard gate.** An item is visible here only
   if the Connection that produced it is authorized for this Channel - by the
   Channel itself or inherited from its Group, Class or Workspace
   (channel_authorization). Never inferred, never widened.

   Until Phase 3 this matched on *provider* instead, because an AttentionItem
   had no link back to its source. That made an admin sharing their mailbox
   read as "this channel may see any Gmail in the workspace", so a member's
   private mail could surface in a shared briefing. Items now carry
   `connection_id` and are gated on it, like every other channel surface.

2. **Resource allow-lists are enforced wherever the item has an
   allow-listable resource.** A Drive-sourced item must match an allow-listed
   file/folder if that connection has any allow-list entries.

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

import structlog
from sqlalchemy.orm import Session

from app.agents.llm import LLMClient, LLMError
from app.models.attention_item import AttentionItem, AttentionType
from app.providers.registry import PROVIDER_BY_NAME, RESOURCE_SCOPED_PROVIDERS
from app.services.attention_engine import list_attention
from app.services.channel_authorization import resolve_channel_scope

logger = structlog.get_logger("sentinel.channel_briefing")

# Items carry their own `source_provider`, so the resource-gating decision
# keys off that rather than off the item type - a DEADLINE can come from
# Gmail *or* from a document, and each is gated as its own provider requires.
#
# Both tables come from the provider registry (app/providers): which
# providers are resource-scoped is a fact about the provider, not about this
# module, and it used to be restated here where nothing kept it in sync.


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
    """Everything this Channel is authorized for, resolved once per request.

    Phase 2z: delegates to channel_authorization so the scope is the union
    across the Channel's own connections plus those shared at its Group and
    Class. Feed, Briefing, Insights and Knowledge all read through here, so
    inheritance reaches every one of them without a change at their call
    sites.
    """
    return resolve_channel_scope(session, team_id)


def _is_visible_in_channel(session: Session, item: AttentionItem, scope: dict) -> bool:
    # Manual reminders are personal by definition - they belong to whoever
    # created them, not to a shared channel view.
    if item.type == AttentionType.MANUAL:
        return False

    # The connection that produced this item must itself be authorized here
    # (Phase 3). This used to match on *provider*, which meant "the channel
    # may see Gmail" resolved to "the channel may see every mailbox connected
    # in this workspace" - a member's private mail included. An item with no
    # connection recorded is not visible: fail-closed, as everywhere else.
    if item.connection_id is None or item.connection_id not in scope["connections"]:
        return False

    provider = PROVIDER_BY_NAME.get(item.source_provider or "")
    if provider in RESOURCE_SCOPED_PROVIDERS:
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
