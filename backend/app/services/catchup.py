"""Phase 2q: Catch Me Up - what changed since you last looked.

The delta itself is a cheap deterministic diff over already-synced data
(counts + a few real titles). The LLM's only job is narrating those facts
into <=3 human sentences - and if the LLM is unavailable (free-tier rate
limits are a real, recurring constraint here), a deterministic sentence is
returned instead, so the feature degrades to "less charming", never to
"broken".
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.llm import LLMClient, LLMError
from app.models.attention_item import AttentionItem, AttentionState
from app.models.finding import Finding
from app.models.signal import Signal, SignalType
from app.models.workspace import Membership

logger = structlog.get_logger("sentinel.catchup")

MAX_WINDOW_DAYS = 7  # cap the diff window so a month away doesn't produce a novel
MIN_GAP_HOURS = 12  # below this, there's nothing worth catching up on


def build_catchup(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    """Compute the since-last-seen delta, narrate it, and advance the
    last-seen marker. Returns {"narrative": None} when the gap is too small
    to be worth a card."""
    now = datetime.now(timezone.utc)
    membership = session.execute(
        select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
    ).scalar_one_or_none()

    last_seen = membership.last_seen_at if membership else None
    since = max(last_seen or (now - timedelta(days=MAX_WINDOW_DAYS)), now - timedelta(days=MAX_WINDOW_DAYS))
    gap_hours = (now - since).total_seconds() / 3600

    if membership is not None:
        membership.last_seen_at = now
        session.commit()

    if gap_hours < MIN_GAP_HOURS:
        return {"since": since.isoformat(), "gap_hours": round(gap_hours, 1), "narrative": None, "facts": {}}

    facts = _collect_facts(session, workspace_id, since, now)
    if not any(v for k, v in facts.items() if isinstance(v, int)):
        return {"since": since.isoformat(), "gap_hours": round(gap_hours, 1), "narrative": None, "facts": facts}

    narrative = _narrate(facts, gap_hours)
    return {"since": since.isoformat(), "gap_hours": round(gap_hours, 1), "narrative": narrative, "facts": facts}


def _collect_facts(session: Session, workspace_id: uuid.UUID, since: datetime, now: datetime) -> dict:
    email_signals = session.execute(
        select(Signal).where(
            Signal.workspace_id == workspace_id, Signal.type == SignalType.EMAIL, Signal.occurred_at >= since
        )
    ).scalars().all()
    important_titles = []
    for s in email_signals:
        labels = set(s.payload.get("label_ids") or [])
        promotional = bool(labels & {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "SPAM"})
        if "STARRED" in labels or ("IMPORTANT" in labels and not promotional):
            important_titles.append(s.payload.get("subject") or "(no subject)")

    meetings = session.execute(
        select(Signal).where(Signal.workspace_id == workspace_id, Signal.type == SignalType.CALENDAR_EVENT)
    ).scalars().all()
    upcoming_titles = []
    for s in meetings:
        try:
            start = datetime.fromisoformat(s.payload.get("start") or "")
        except ValueError:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if s.payload.get("status") != "cancelled" and now <= start <= now + timedelta(hours=24):
            upcoming_titles.append(s.payload.get("title") or "Untitled meeting")

    prs = session.execute(
        select(Signal).where(Signal.workspace_id == workspace_id, Signal.type == SignalType.PR, Signal.occurred_at >= since)
    ).scalars().all()

    new_findings = session.execute(
        select(Finding).where(Finding.workspace_id == workspace_id, Finding.created_at >= since, Finding.severity >= 0.6)
    ).scalars().all()

    attention_new = session.execute(
        select(AttentionItem).where(AttentionItem.workspace_id == workspace_id, AttentionItem.state == AttentionState.NEW)
    ).scalars().all()

    return {
        "new_emails": len(email_signals),
        "new_important_emails": len(important_titles),
        "important_email_subjects": important_titles[:3],
        "meetings_next_24h": len(upcoming_titles),
        "upcoming_meeting_titles": upcoming_titles[:3],
        "new_prs": len(prs),
        "new_high_severity_findings": len(new_findings),
        "open_attention_items": len(attention_new),
    }


def _narrate(facts: dict, gap_hours: float) -> str:
    away = f"{round(gap_hours)} hours" if gap_hours < 48 else f"{round(gap_hours / 24)} days"
    try:
        result = LLMClient().complete_json(
            system=(
                "You are Sentinel, an operations assistant. Write a 'catch me up' summary of what "
                "happened while the user was away. STRICT RULES: maximum 3 short sentences; mention only "
                "facts present in the provided data (counts and titles) - never invent specifics; plain "
                "text, no markdown, no greetings; lead with the most actionable thing. "
                'Return JSON: {"narrative": "..."}'
            ),
            user=f"User was away for {away}. Data: {facts}",
        )
        narrative = (result.get("narrative") or "").strip()
        if narrative:
            return narrative
    except LLMError:
        logger.warning("catchup_llm_unavailable_using_fallback")

    # Deterministic fallback - less charming, never broken.
    parts = []
    if facts["new_important_emails"]:
        parts.append(f"{facts['new_important_emails']} important emails arrived")
    if facts["meetings_next_24h"]:
        parts.append(f"{facts['meetings_next_24h']} meetings in the next 24h")
    if facts["new_high_severity_findings"]:
        parts.append(f"{facts['new_high_severity_findings']} new high-severity findings")
    if facts["open_attention_items"]:
        parts.append(f"{facts['open_attention_items']} items need your attention")
    return f"While you were away ({away}): " + "; ".join(parts) + "." if parts else f"Quiet while you were away ({away}) - nothing urgent came in."
