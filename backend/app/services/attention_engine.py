"""Phase 2p: deterministic attention detection.

Rules find candidates from already-synced Signals and Findings; no LLM is
involved anywhere in this module (see attention_item.py's docstring for
why). Precision over recall throughout: each detector is deliberately
conservative and capped - five right items beat fifteen maybe-items,
because three false "urgent!"s is how an attention feature loses the
user's trust permanently.

Refresh is idempotent and safe to run on every sync cycle:
- upsert by (workspace_id, dedupe_key) - facts update in place
- rows in DONE/DISMISSED are never touched again by detection
- detected items whose underlying fact resolved itself (email read,
  meeting over, PR merged, finding gone stale) auto-complete, so the list
  stays honest without the user having to garbage-collect it
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.finding import Finding
from app.models.signal import Signal, SignalType

logger = structlog.get_logger("sentinel.attention")

EMAIL_LOOKBACK_DAYS = 7
EMAIL_CAP = 5
MEETING_HORIZON_HOURS = 24
STALE_PR_DAYS = 4
STALE_PR_CAP = 5
FINDING_MIN_SEVERITY = 0.6
FINDING_LOOKBACK_DAYS = 3
MEETING_EXPIRY_GRACE_HOURS = 2


def refresh_attention(session: Session, workspace_id: uuid.UUID) -> list[AttentionItem]:
    """Run every detector, reconcile with existing rows, return the current
    actionable list (NEW items, sorted). Called after each ingestion cycle
    and from the on-demand refresh endpoint."""
    now = datetime.now(timezone.utc)

    detected: dict[str, dict] = {}
    for candidate in (
        _detect_important_emails(session, workspace_id, now)
        + _detect_upcoming_meetings(session, workspace_id, now)
        + _detect_stale_prs(session, workspace_id, now)
        + _detect_findings(session, workspace_id, now)
    ):
        detected[candidate["dedupe_key"]] = candidate

    existing_detected = session.execute(
        select(AttentionItem).where(
            AttentionItem.workspace_id == workspace_id, AttentionItem.origin == AttentionOrigin.DETECTED
        )
    ).scalars().all()

    for item in existing_detected:
        candidate = detected.pop(item.dedupe_key, None)
        if candidate is not None:
            # Fact still holds. Refresh the mutable facts, but only a row
            # the user hasn't acted on - DONE/DISMISSED stay resolved, and
            # SNOOZED keeps its snooze (facts update, state doesn't).
            if item.state in (AttentionState.NEW, AttentionState.SNOOZED):
                item.title = candidate["title"]
                item.why = candidate["why"]
                item.priority = candidate["priority"]
                item.due_at = candidate.get("due_at")
                item.evidence_url = candidate.get("evidence_url")
        else:
            # Fact no longer qualifies (email read, meeting over, PR
            # merged...) - auto-complete unresolved rows so the list stays
            # honest. User-resolved rows are left exactly as they are.
            if item.state in (AttentionState.NEW, AttentionState.SNOOZED):
                item.state = AttentionState.DONE

    for candidate in detected.values():  # genuinely new facts
        session.add(
            AttentionItem(
                workspace_id=workspace_id,
                origin=AttentionOrigin.DETECTED,
                state=AttentionState.NEW,
                **candidate,
            )
        )

    session.commit()
    return list_attention(session, workspace_id)


def list_attention(session: Session, workspace_id: uuid.UUID, *, states: list[AttentionState] | None = None) -> list[AttentionItem]:
    """Snooze resurfacing happens lazily here (no scheduler needed): a
    snoozed item whose time has come flips back to NEW on read."""
    now = datetime.now(timezone.utc)
    items = session.execute(
        select(AttentionItem).where(AttentionItem.workspace_id == workspace_id)
    ).scalars().all()

    changed = False
    for item in items:
        if item.state == AttentionState.SNOOZED and item.snoozed_until is not None and item.snoozed_until <= now:
            item.state = AttentionState.NEW
            item.snoozed_until = None
            changed = True
    if changed:
        session.commit()

    wanted = set(states) if states else {AttentionState.NEW}
    result = [i for i in items if i.state in wanted]
    # Highest priority first; due-soonest breaks ties; newest last resort.
    result.sort(key=lambda i: (-i.priority, i.due_at or datetime.max.replace(tzinfo=timezone.utc), i.created_at))
    return result


def _age_days(now: datetime, then: datetime) -> int:
    return max(0, int((now - then).total_seconds() // 86400))


def _detect_important_emails(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    since = now - timedelta(days=EMAIL_LOOKBACK_DAYS)
    signals = session.execute(
        select(Signal)
        .where(Signal.workspace_id == workspace_id, Signal.type == SignalType.EMAIL, Signal.occurred_at >= since)
        .order_by(Signal.occurred_at.desc())
    ).scalars().all()

    candidates = []
    for s in signals:
        labels = set(s.payload.get("label_ids") or [])
        if "UNREAD" not in labels:
            continue
        starred = "STARRED" in labels
        important = "IMPORTANT" in labels
        # Gmail marks a LOT of routine mail IMPORTANT - requiring the
        # non-promotional inbox categories keeps precision honest.
        promotional = bool(labels & {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "SPAM"})
        if not (starred or (important and not promotional)):
            continue

        sender = (s.payload.get("from") or "unknown").split("<")[0].strip().strip('"')
        age = _age_days(now, s.occurred_at)
        reason = "Starred" if starred else "Marked important"
        candidates.append(
            {
                "dedupe_key": f"email:{s.external_id}",
                "type": AttentionType.IMPORTANT_EMAIL,
                "source_provider": "gmail",
                "title": s.payload.get("subject") or "(no subject)",
                "why": f"{reason}, still unread — from {sender}, {age}d ago" if age else f"{reason}, still unread — from {sender}, today",
                "evidence_url": f"https://mail.google.com/mail/u/0/#all/{s.external_id}",
                "priority": 0.75 if starred else 0.6,
            }
        )
        if len(candidates) >= EMAIL_CAP:
            break
    return candidates


def _detect_upcoming_meetings(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    signals = session.execute(
        select(Signal).where(Signal.workspace_id == workspace_id, Signal.type == SignalType.CALENDAR_EVENT)
    ).scalars().all()

    candidates = []
    horizon = now + timedelta(hours=MEETING_HORIZON_HOURS)
    for s in signals:
        if s.payload.get("status") == "cancelled":
            continue
        start_raw = s.payload.get("start")
        if not start_raw:
            continue
        try:
            start = datetime.fromisoformat(start_raw)
        except ValueError:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if not (now - timedelta(minutes=30) <= start <= horizon):
            continue

        hours_away = (start - now).total_seconds() / 3600
        when = "starting now" if hours_away < 0.25 else f"in {round(hours_away)}h" if hours_away >= 1 else f"in {round(hours_away * 60)}min"
        attendees = s.payload.get("attendee_count") or 0
        why = f"Starts {when}" + (f" · {attendees} attendees" if attendees else "") + (" · has Meet link" if s.payload.get("meet_url") else "")
        candidates.append(
            {
                # Recurring events keep one external_id per occurrence set -
                # the start date in the key gives each occurrence its own row.
                "dedupe_key": f"meeting:{s.external_id}:{start.date().isoformat()}",
                "type": AttentionType.UPCOMING_MEETING,
                "source_provider": "google_calendar",
                "title": s.payload.get("title") or "Untitled meeting",
                "why": why,
                "evidence_url": s.payload.get("url"),
                "priority": 0.8,
                "due_at": start,
            }
        )
    return candidates


def _detect_stale_prs(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    threshold = now - timedelta(days=STALE_PR_DAYS)
    signals = session.execute(
        select(Signal)
        .where(Signal.workspace_id == workspace_id, Signal.type == SignalType.PR, Signal.occurred_at <= threshold)
        .order_by(Signal.occurred_at.asc())
    ).scalars().all()

    candidates = []
    for s in signals:
        if s.payload.get("merged_at") or s.payload.get("closed_at"):
            continue
        age = _age_days(now, s.occurred_at)
        candidates.append(
            {
                "dedupe_key": f"pr:{s.external_id}",
                "type": AttentionType.STALE_PR,
                "source_provider": "github",
                "title": s.payload.get("title") or f"PR #{s.payload.get('number', '?')}",
                "why": f"Open {age} days without merging — by {s.actor}",
                "evidence_url": s.payload.get("url"),
                "priority": 0.55,
            }
        )
        if len(candidates) >= STALE_PR_CAP:
            break
    return candidates


def _detect_findings(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    since = now - timedelta(days=FINDING_LOOKBACK_DAYS)
    findings = session.execute(
        select(Finding)
        .where(Finding.workspace_id == workspace_id, Finding.severity >= FINDING_MIN_SEVERITY, Finding.created_at >= since)
        .order_by(Finding.severity.desc())
    ).scalars().all()

    return [
        {
            "dedupe_key": f"finding:{f.id}",
            "type": AttentionType.FINDING,
            "source_provider": "agent",
            "title": f.summary,
            "why": f"Flagged by the {f.agent} agent · severity {round(f.severity * 100)}%",
            "evidence_url": f"/findings/{f.id}",  # internal route - the finding detail page
            "priority": f.severity,
        }
        for f in findings
    ]
