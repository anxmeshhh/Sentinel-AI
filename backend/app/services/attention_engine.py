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

from app.models.agent_run import AgentRun
from app.models.attention_item import AttentionItem, AttentionOrigin, AttentionState, AttentionType
from app.models.connection import Connection, Provider, ResourcePriority
from app.models.finding import AgentFinding
from app.models.signal import Signal, SignalType
from app.services.deadline_parser import find_deadline
from app.services.mail_signals import extract_address, noise_reason, sender_counts

logger = structlog.get_logger("sentinel.attention")

EMAIL_LOOKBACK_DAYS = 7
EMAIL_CAP = 5
MEETING_HORIZON_HOURS = 24
STALE_PR_DAYS = 4
STALE_PR_CAP = 5
DEADLINE_CAP = 8
FINDING_MIN_SEVERITY = 0.6
FINDING_LOOKBACK_DAYS = 3
MEETING_EXPIRY_GRACE_HOURS = 2

# --- Slack findings (Phase 3) ----------------------------------------------
# Deterministic detectors over ingested Slack signals. Windows are short
# because chat is fast-moving: a blocker or a mention matters now, not last
# week. Caps keep a busy workspace from flooding the briefing.
CONVERSATION_MENTION_LOOKBACK_DAYS = 3
CONVERSATION_FLAG_LOOKBACK_DAYS = 3
CONVERSATION_URGENT_WINDOW_HOURS = 12
CONVERSATION_URGENT_MIN = 3  # this many flagged messages in the window is a burst
CONVERSATION_CAP = 5
# Lexicon slices used only for severity - which flavour of urgent this is. The
# words themselves are matched at ingest (services/slack_signals.py).
_BLOCKER_TERMS = {"blocked", "blocker"}
_INCIDENT_TERMS = {"incident", "outage", "down", "escalate", "escalation"}


# Every chat provider whose channels produce conversation signals. The three
# detectors below are shared across all of them: a blocker, a mention in a
# critical channel and an incident forming read identically whether they
# happened in Slack or Teams, so there is one implementation, not one per
# provider (the N=2 rule - Teams added none of its own detection logic).
CONVERSATION_PROVIDERS = (Provider.SLACK, Provider.MICROSOFT_TEAMS)


def _conversation_permalink(conn: Connection, sig: Signal) -> str | None:
    """A deep link to the exact message a finding came from.

    Teams messages carry their own webUrl at ingest, so it is used verbatim.
    Slack has no per-message URL in the payload, but its deep-link form is
    stable and domain-agnostic, so it is constructed from the ids."""
    url = (sig.payload or {}).get("url")
    if url:
        return url
    if conn.provider is Provider.SLACK:
        return f"https://slack.com/app_redirect?channel={conn.repo}&message_ts={sig.external_id}"
    return None


def _conversation_signals(session: Session, workspace_id: uuid.UUID, sig_type: SignalType, since: datetime):
    """Signals of one type from monitored (non-paused) channels of ANY chat
    provider, newest first, joined to their channel so priority and name are on
    hand."""
    return session.execute(
        select(Signal, Connection)
        .join(Connection, Connection.id == Signal.connection_id)
        .where(
            Signal.workspace_id == workspace_id,
            Signal.type == sig_type,
            Signal.occurred_at >= since,
            Connection.provider.in_(CONVERSATION_PROVIDERS),
            Connection.paused_at.is_(None),
        )
        .order_by(Signal.occurred_at.desc())
    ).all()


def _detect_conversation_priority_mentions(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """A mention in a channel a person marked CRITICAL. The classification is
    what makes it high-priority: the chat app already notifies plain
    mentions, so surfacing every one would just duplicate it. Only the ones in channels
    declared to matter reach the briefing."""
    rows = _conversation_signals(session, workspace_id, SignalType.MENTION, now - timedelta(days=CONVERSATION_MENTION_LOOKBACK_DAYS))
    candidates: list[dict] = []
    for sig, conn in rows:
        if conn.priority is not ResourcePriority.CRITICAL:
            continue
        age = _age_days(now, sig.occurred_at)
        snippet = (sig.payload or {}).get("snippet") or ""
        candidates.append({
            "dedupe_key": f"{conn.provider.value}_mention:{sig.external_id}",
            "connection_id": conn.id,
            "type": AttentionType.CONVERSATION_MENTION,
            "source_provider": conn.provider.value,
            "title": f"Mention in {conn.full_name}",
            "why": f"Mentioned in a critical channel {('today' if age == 0 else f'{age}d ago')}: {snippet[:140]}",
            "evidence_url": _conversation_permalink(conn, sig),
            "priority": 0.75,
        })
        if len(candidates) >= CONVERSATION_CAP:
            break
    return candidates


def _detect_conversation_blockers(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """A message flagged as a blocker (the lexicon matched 'blocked'/'blocker').
    One finding per flagged message; it auto-resolves when the message ages out
    of the window."""
    rows = _conversation_signals(session, workspace_id, SignalType.FLAGGED_MESSAGE, now - timedelta(days=CONVERSATION_FLAG_LOOKBACK_DAYS))
    candidates: list[dict] = []
    for sig, conn in rows:
        if not (set((sig.payload or {}).get("matched") or []) & _BLOCKER_TERMS):
            continue
        snippet = (sig.payload or {}).get("snippet") or ""
        candidates.append({
            "dedupe_key": f"{conn.provider.value}_blocker:{sig.external_id}",
            "connection_id": conn.id,
            "type": AttentionType.CONVERSATION_BLOCKER,
            "source_provider": conn.provider.value,
            "title": f"Possible blocker in {conn.full_name}",
            "why": f"Flagged as blocked in {conn.full_name}: {snippet[:140]}",
            "evidence_url": _conversation_permalink(conn, sig),
            "priority": 0.75 if conn.priority is ResourcePriority.CRITICAL else 0.6,
        })
        if len(candidates) >= CONVERSATION_CAP:
            break
    return candidates


def _detect_conversation_urgent(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """A burst of urgent signals in one channel - repeated urgency, or a
    multi-person incident forming. Aggregated to ONE finding per channel, so a
    storm of messages is one situation and not fifty items, and it auto-resolves
    when the burst falls back below the threshold."""
    rows = _conversation_signals(session, workspace_id, SignalType.FLAGGED_MESSAGE, now - timedelta(hours=CONVERSATION_URGENT_WINDOW_HOURS))

    by_channel: dict[uuid.UUID, dict] = {}
    for sig, conn in rows:
        grp = by_channel.setdefault(conn.id, {"conn": conn, "sigs": []})
        grp["sigs"].append(sig)

    candidates: list[dict] = []
    for grp in by_channel.values():
        conn, sigs = grp["conn"], grp["sigs"]
        actors = {s.actor for s in sigs if s.actor}
        terms: set[str] = set()
        for s in sigs:
            terms |= set((s.payload or {}).get("matched") or [])
        incident = bool(terms & _INCIDENT_TERMS) and len(actors) >= 2
        if not (len(sigs) >= CONVERSATION_URGENT_MIN or incident):
            continue
        if incident:
            title = f"Possible incident forming in {conn.full_name}"
            why = (f"{len(sigs)} urgent messages from {len(actors)} people in the last "
                   f"{CONVERSATION_URGENT_WINDOW_HOURS}h — {', '.join(sorted(terms & _INCIDENT_TERMS))}")
            priority = 0.85
        else:
            title = f"Repeated urgent signals in {conn.full_name}"
            why = f"{len(sigs)} messages flagged urgent in {conn.full_name} in the last {CONVERSATION_URGENT_WINDOW_HOURS}h"
            priority = 0.65
        candidates.append({
            "dedupe_key": f"{conn.provider.value}_urgent:{conn.repo}",  # one per channel
            "connection_id": conn.id,
            "type": AttentionType.CONVERSATION_URGENT,
            "source_provider": conn.provider.value,
            "title": title,
            "why": why,
            "evidence_url": _conversation_permalink(conn, sigs[0]),
            "priority": priority,
        })
    return candidates


# --- Work items (TASK signals) ---------------------------------------------
# Provider-agnostic on purpose: these read SignalType.TASK, so Microsoft To Do
# today and Planner or Jira later fire the same two findings with no new code.
# Completed tasks are excluded at the source - a done task is never a finding.
TASK_CAP = 8


def _open_task_signals(session: Session, workspace_id: uuid.UUID):
    """Incomplete tasks from non-paused connections, soonest-due first."""
    rows = session.execute(
        select(Signal, Connection)
        .join(Connection, Connection.id == Signal.connection_id)
        .where(
            Signal.workspace_id == workspace_id,
            Signal.type == SignalType.TASK,
            Connection.paused_at.is_(None),
        )
        .order_by(Signal.occurred_at.asc())
    ).all()
    return [(sig, conn) for sig, conn in rows if not (sig.payload or {}).get("completed")]


def _detect_overdue_tasks(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """A task whose due date has passed and which is not done. The clearest
    finding a task list can produce - no judgement needed, just a date."""
    candidates: list[dict] = []
    for sig, conn in _open_task_signals(session, workspace_id):
        payload = sig.payload or {}
        due = _parse_iso(payload.get("due_at"))
        if due is None or due >= now:
            continue
        days = max(1, (now - due).days)
        high = payload.get("importance") == "high"
        candidates.append({
            "dedupe_key": f"task_overdue:{sig.external_id}",
            "connection_id": conn.id,
            "type": AttentionType.TASK_OVERDUE,
            "source_provider": conn.provider.value,
            "title": f"Overdue: {payload.get('title') or 'task'}",
            "why": (f"Was due {days}d ago in {payload.get('list') or 'your tasks'}"
                    + (" — marked high importance" if high else "")),
            "evidence_url": None,
            # An overdue task the person flagged important outranks the rest.
            "priority": 0.8 if high else 0.65,
            "due_at": due,
        })
        if len(candidates) >= TASK_CAP:
            break
    return candidates


def _detect_tasks_due_today(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """Due today and not done - actionable while it is still today, and it
    auto-resolves tomorrow by becoming overdue instead."""
    candidates: list[dict] = []
    for sig, conn in _open_task_signals(session, workspace_id):
        payload = sig.payload or {}
        due = _parse_iso(payload.get("due_at"))
        if due is None or due < now or due.date() != now.date():
            continue
        high = payload.get("importance") == "high"
        candidates.append({
            "dedupe_key": f"task_due_today:{sig.external_id}",
            "connection_id": conn.id,
            "type": AttentionType.TASK_DUE_TODAY,
            "source_provider": conn.provider.value,
            "title": f"Due today: {payload.get('title') or 'task'}",
            "why": f"Due today in {payload.get('list') or 'your tasks'}" + (" — high importance" if high else ""),
            "evidence_url": None,
            "priority": 0.7 if high else 0.55,
            "due_at": due,
        })
        if len(candidates) >= TASK_CAP:
            break
    return candidates


def _parse_iso(raw) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)



# How long an important, unread message sits before it stops being "recent mail"
# and starts being something that fell through the cracks. Deliberately well
# past EMAIL_LOOKBACK_DAYS so the two detectors never describe the same message.
UNANSWERED_MAIL_DAYS = 14
# Below this it is an untidy inbox, not an operational problem. Chosen so the
# finding means "a habit has formed", not "you have unread mail".
UNANSWERED_MAIL_MIN = 3


def _detect_unanswered_mail(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """Important mail that arrived a while ago and was never opened.

    The gap this closes: _detect_important_emails only looks back
    EMAIL_LOOKBACK_DAYS, which is right for "what just arrived" but exactly
    backwards for "what got dropped" - a flagged message from three weeks ago is
    MORE concerning than one from this morning, not less. Measured on real data:
    27 messages qualified as unread+important while the recency detector could
    see only 1.

    Aggregated to ONE finding per mailbox on purpose. Twenty-seven separate
    items would be noise and would drown the feed; a single "these are piling
    up" is the operational fact. It auto-resolves when they are read or the
    count falls back below the threshold.
    """
    cutoff = now - timedelta(days=UNANSWERED_MAIL_DAYS)
    rows = session.execute(
        select(Signal, Connection)
        .join(Connection, Connection.id == Signal.connection_id)
        .where(
            Signal.workspace_id == workspace_id,
            Signal.type == SignalType.EMAIL,
            Signal.occurred_at < cutoff,
            Connection.paused_at.is_(None),
        )
        .order_by(Signal.occurred_at.asc())
    ).all()

    # Grouped per mailbox connection: two mailboxes with three stale messages
    # each is two situations, not one combined six.
    by_connection: dict = {}
    for sig, conn in rows:
        payload = sig.payload or {}
        labels = set(payload.get("label_ids") or [])
        if "UNREAD" not in labels:
            continue
        starred = "STARRED" in labels
        important = "IMPORTANT" in labels
        # The same precision rule the recency detector uses - promotional mail
        # marked "important" by the provider is not an operational signal.
        if bool(labels & {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "SPAM"}) and not starred:
            continue
        if not (starred or important):
            continue
        by_connection.setdefault(conn.id, {"conn": conn, "items": []})["items"].append((sig, payload))

    candidates: list[dict] = []
    for group in by_connection.values():
        conn, items = group["conn"], group["items"]
        if len(items) < UNANSWERED_MAIL_MIN:
            continue
        oldest_sig, oldest_payload = items[0]
        oldest_days = _age_days(now, oldest_sig.occurred_at)
        subject = (oldest_payload.get("subject") or "(no subject)")[:80]
        candidates.append({
            # One row per mailbox, so re-running updates rather than stacking.
            "dedupe_key": f"unanswered_mail:{conn.id}",
            "connection_id": conn.id,
            "type": AttentionType.UNANSWERED_MAIL,
            "source_provider": conn.provider.value,
            "title": f"{len(items)} important messages are still unread",
            "why": (f"Unread and flagged important for over {UNANSWERED_MAIL_DAYS} days in "
                    f"{conn.org} — the oldest is {oldest_days}d old: “{subject}”"),
            "evidence_url": None,
            # Below critical on purpose: this is a backlog, not an emergency.
            # It rises with the age of the oldest message, capped.
            "priority": min(0.7, 0.45 + 0.01 * oldest_days),
        })
    return candidates


def refresh_attention(
    session: Session, workspace_id: uuid.UUID, *, viewer_user_id: uuid.UUID | None = None
) -> list[AttentionItem]:
    """Run every detector, reconcile with existing rows, return the current
    actionable list (NEW items, sorted). Called after each ingestion cycle
    and from the on-demand refresh endpoint.

    Detection always covers the whole workspace - every connection's data is
    re-examined. `viewer_user_id` only narrows what is *returned*, so the
    caller refreshing gets their own list back and not a teammate's.
    """
    now = datetime.now(timezone.utc)

    detected: dict[str, dict] = {}
    for candidate in (
        _detect_important_emails(session, workspace_id, now)
        + _detect_unanswered_mail(session, workspace_id, now)
        + _detect_upcoming_meetings(session, workspace_id, now)
        + _detect_stale_prs(session, workspace_id, now)
        + _detect_findings(session, workspace_id, now)
        + _detect_deadlines(session, workspace_id, now)
        + _detect_conversation_priority_mentions(session, workspace_id, now)
        + _detect_conversation_blockers(session, workspace_id, now)
        + _detect_conversation_urgent(session, workspace_id, now)
        + _detect_overdue_tasks(session, workspace_id, now)
        + _detect_tasks_due_today(session, workspace_id, now)
        # Existing-data intelligence. Deterministic, no LLM, and each one
        # produces its own AttentionType so the Situation Engine can correlate
        # by kind rather than lumping them into a generic "finding".
        + _detect_meeting_conflicts(session, workspace_id, now)
        + _detect_meeting_overload(session, workspace_id, now)
        + _detect_slow_merges(session, workspace_id, now)
        + _detect_review_bottleneck(session, workspace_id, now)
        + _detect_bus_factor(session, workspace_id, now)
        + _detect_stale_issues(session, workspace_id, now)
        + _detect_stale_documents(session, workspace_id, now)
    ):
        detected[candidate["dedupe_key"]] = candidate

    _suppress_weaker_duplicates(detected)

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
            # Set regardless of state: this is provenance, not a fact the
            # user has acted on, and a row left NULL is a row that stays
            # invisible everywhere it is now gated (Phase 3).
            item.connection_id = candidate.get("connection_id")
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
    return list_attention(session, workspace_id, viewer_user_id=viewer_user_id)


def _suppress_weaker_duplicates(detected: dict[str, dict]) -> None:
    """One underlying fact must produce exactly one item.

    An email like "Invoice INV-2291 is due in 3 days" legitimately trips two
    detectors - it's both unread-and-important *and* a dated commitment.
    Showing it twice is precisely the noise that makes an attention list
    feel untrustworthy, so the deadline (which carries the date and the
    higher priority) wins and the plain email item is dropped. Mutates in
    place, before anything is written.
    """
    deadline_sources = {key.split(":", 1)[1] for key in detected if key.startswith("deadline:")}
    for source_id in deadline_sources:
        detected.pop(f"email:{source_id}", None)


def list_attention(
    session: Session,
    workspace_id: uuid.UUID,
    *,
    states: list[AttentionState] | None = None,
    viewer_user_id: uuid.UUID | None = None,
) -> list[AttentionItem]:
    """Snooze resurfacing happens lazily here (no scheduler needed): a
    snoozed item whose time has come flips back to NEW on read.

    `viewer_user_id` narrows the list to that person's *own* attention: items
    produced by a connection they own, plus manual items they created. Pass it
    for anything a single human reads as "my Sentinel".

    Omitting it returns every item in the workspace, which is correct for
    exactly one caller - channel_briefing, which then applies the channel's
    own authorization (see that module). A team workspace holds attention
    items derived from several members' connections, so an unfiltered list is
    never safe to hand to a person directly.
    """
    now = datetime.now(timezone.utc)
    items = session.execute(
        select(AttentionItem).where(AttentionItem.workspace_id == workspace_id)
    ).scalars().all()

    if viewer_user_id is not None:
        mine = set(session.execute(
            select(Connection.id).where(
                Connection.workspace_id == workspace_id, Connection.user_id == viewer_user_id
            )
        ).scalars())
        # Fail-closed on both sides: a detected item with no connection
        # recorded belongs to nobody and is shown to nobody; a manual item
        # belongs to its author alone.
        items = [
            i for i in items
            if (i.created_by_user_id == viewer_user_id if i.origin == AttentionOrigin.MANUAL else i.connection_id in mine)
        ]

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


def owns_attention_item(
    session: Session, item: AttentionItem, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """Whether this attention item is the caller's own.

    The same rule `list_attention(viewer_user_id=...)` applies to reads, stated
    here so a WRITE can never be authorized more loosely than the read that
    revealed the item. It was: `PATCH /attention/{id}` checked only that the
    item was in the caller's workspace, so any member of a shared workspace
    could resolve, snooze or dismiss an item detected from a teammate's
    mailbox - an item they could not themselves see, because reads have always
    been narrowed by viewer.

    Fail-closed on both sides, exactly as the read filter does: a detected item
    with no connection recorded belongs to nobody, and a manual item belongs to
    its author alone.
    """
    if item.workspace_id != workspace_id:
        return False
    if item.origin == AttentionOrigin.MANUAL:
        return item.created_by_user_id == user_id
    if item.connection_id is None:
        return False
    owner_id = session.execute(
        select(Connection.user_id).where(Connection.id == item.connection_id)
    ).scalar_one_or_none()
    return owner_id == user_id


def _age_days(now: datetime, then: datetime) -> int:
    return max(0, int((now - then).total_seconds() // 86400))


def _detect_important_emails(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    since = now - timedelta(days=EMAIL_LOOKBACK_DAYS)
    signals = session.execute(
        select(Signal)
        .where(Signal.workspace_id == workspace_id, Signal.type == SignalType.EMAIL, Signal.occurred_at >= since)
        .order_by(Signal.occurred_at.desc())
    ).scalars().all()

    # Repetition is the strongest noise signal (Phase 2v), and it can only
    # be seen across the whole window - so counts are computed once here.
    counts = sender_counts([s.payload for s in signals])

    candidates = []
    seen_subjects: set[tuple[str, str]] = set()
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

        # Starring is an explicit human judgment about this specific
        # message. It always outranks our heuristics - we never filter out
        # something the user personally marked.
        if not starred and noise_reason(s.payload, counts) is not None:
            continue

        # The same notification sent twice ("your domain is expiring")
        # should occupy one slot, not two.
        subject = s.payload.get("subject") or "(no subject)"
        fingerprint = (extract_address(s.payload.get("from")) or "", subject.strip().lower())
        if fingerprint in seen_subjects:
            continue
        seen_subjects.add(fingerprint)

        sender = (s.payload.get("from") or "unknown").split("<")[0].strip().strip('"')
        age = _age_days(now, s.occurred_at)
        reason = "Starred" if starred else "Marked important"
        candidates.append(
            {
                "dedupe_key": f"email:{s.external_id}",
                "connection_id": s.connection_id,
                "type": AttentionType.IMPORTANT_EMAIL,
                "source_provider": "gmail",
                "title": subject,
                "why": f"{reason}, still unread — from {sender}, {age}d ago" if age else f"{reason}, still unread — from {sender}, today",
                "evidence_url": f"https://mail.google.com/mail/u/0/#all/{s.external_id}",
                "priority": 0.75 if starred else 0.6,
            }
        )
        if len(candidates) >= EMAIL_CAP:
            break
    return candidates


def _detect_upcoming_meetings(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    # Joined to Connection so each finding can be attributed to the provider it
    # actually came from. This used to be hardcoded "google_calendar", which was
    # already wrong for Outlook (its meetings never reached the Outlook rail,
    # since the workspace intelligence endpoint filters findings by provider)
    # and would have been wrong again for Zoom. The detector itself stays
    # provider-neutral - it reads CALENDAR_EVENT and nothing else.
    rows = session.execute(
        select(Signal, Connection)
        .join(Connection, Connection.id == Signal.connection_id)
        .where(Signal.workspace_id == workspace_id, Signal.type == SignalType.CALENDAR_EVENT)
    ).all()

    candidates = []
    horizon = now + timedelta(hours=MEETING_HORIZON_HOURS)
    for s, conn in rows:
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
        # None means "this provider does not tell us" (Zoom's meeting list has no
        # roster), which is different from 0. Only a real count is shown.
        attendees = s.payload.get("attendee_count") or 0
        why = (
            f"Starts {when}"
            + (f" · {attendees} attendees" if attendees else "")
            # Provider-neutral wording: the same sentence is true of a Meet link,
            # a Teams link and a Zoom link, and the payload key is already shared.
            + (" · has a join link" if s.payload.get("meet_url") else "")
        )
        candidates.append(
            {
                # Recurring events keep one external_id per occurrence set -
                # the start date in the key gives each occurrence its own row.
                "dedupe_key": f"meeting:{s.external_id}:{start.date().isoformat()}",
                "connection_id": s.connection_id,
                "type": AttentionType.UPCOMING_MEETING,
                "source_provider": conn.provider.value,
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
                "connection_id": s.connection_id,
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


def _detect_deadlines(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """Phase 2t. Reads email *subjects* (bodies are never stored - see
    gmail_client.py) and document text where it exists. Extraction is
    deterministic and keyword-gated; see deadline_parser.py for why.

    A deadline outranks a plain important-email item, so it wins the dedupe
    when the same message produces both: `deadline:` keys are distinct from
    `email:` keys, and the higher priority sorts it above.
    """
    since = now - timedelta(days=EMAIL_LOOKBACK_DAYS)
    candidates: list[dict] = []

    emails = session.execute(
        select(Signal).where(
            Signal.workspace_id == workspace_id, Signal.type == SignalType.EMAIL, Signal.occurred_at >= since
        ).order_by(Signal.occurred_at.desc())
    ).scalars().all()
    email_counts = sender_counts([s.payload for s in emails])
    for s in emails:
        subject = s.payload.get("subject") or ""
        due = find_deadline(subject, now=now)
        if due is None:
            continue
        # Marketing is full of real dates that aren't the user's deadlines
        # ("IPO closing today", "last chance to book"). Same bulk test as
        # important-email detection, for the same reason (Phase 2v).
        if "STARRED" not in set(s.payload.get("label_ids") or []) and noise_reason(s.payload, email_counts) is not None:
            continue
        sender = (s.payload.get("from") or "unknown").split("<")[0].strip().strip('"')
        candidates.append(
            {
                "dedupe_key": f"deadline:{s.external_id}",
                "connection_id": s.connection_id,
                "type": AttentionType.DEADLINE,
                "source_provider": "gmail",
                "title": subject,
                "why": f"Deadline {_humanize_due(now, due)} — from {sender}",
                "evidence_url": f"https://mail.google.com/mail/u/0/#all/{s.external_id}",
                "priority": _deadline_priority(now, due),
                "due_at": due,
            }
        )

    # Documents: only where content is already present (the seeded demo
    # workspace today). Real Drive content is fetched live and never stored,
    # so scanning it on every sync would mean re-downloading every file -
    # deadline extraction from live documents stays an on-demand AI action.
    documents = session.execute(
        select(Signal).where(Signal.workspace_id == workspace_id, Signal.type == SignalType.DRIVE_FILE)
    ).scalars().all()
    for s in documents:
        content = s.payload.get("content") or ""
        if not content:
            continue
        due = None
        for line in content.splitlines():
            due = find_deadline(line, now=now)
            if due is not None:
                break
        if due is None:
            continue
        candidates.append(
            {
                "dedupe_key": f"deadline:{s.external_id}",
                "connection_id": s.connection_id,
                "type": AttentionType.DEADLINE,
                "source_provider": "google_drive",
                "title": f"Deadline in “{s.payload.get('name') or 'a document'}”",
                "why": f"Deadline {_humanize_due(now, due)} — found in the document",
                "evidence_url": s.payload.get("url"),
                "priority": _deadline_priority(now, due),
                "due_at": due,
            }
        )

    return candidates[:DEADLINE_CAP]


def _humanize_due(now: datetime, due: datetime) -> str:
    days = (due.date() - now.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days <= 14:
        return f"in {days} days"
    return f"on {due.strftime('%d %b')}"


def _deadline_priority(now: datetime, due: datetime) -> float:
    """Closer deadlines rank higher, topping out just under a meeting that's
    already starting - an imminent commitment should lead the list."""
    days = max(0, (due.date() - now.date()).days)
    if days <= 1:
        return 0.9
    if days <= 3:
        return 0.78
    if days <= 7:
        return 0.68
    return 0.58


# --- existing-data intelligence -------------------------------------------
#
# Everything below is computed from signals Sentinel already ingests. No new
# provider, no new field, and no LLM anywhere in this section: each detector
# is arithmetic over stored payloads, so every item it produces traces back to
# a real row. Caps and thresholds stay conservative for the same reason as the
# rest of this module - a wrong "urgent" costs more than a missed one.

MEETING_CONFLICT_CAP = 5
MEETING_OVERLOAD_HOURS = 20  # per 7 days, before a calendar counts as crowded
MEETING_CONFLICT_HORIZON_DAYS = 14


def _event_window(payload: dict) -> tuple[datetime, datetime] | None:
    """A calendar event's real span, or None when it is unusable or cancelled."""
    if (payload.get("status") or "confirmed") == "cancelled":
        return None
    start_raw, end_raw = payload.get("start"), payload.get("end")
    if not start_raw or not end_raw:
        return None
    # All-day events carry a date, not a time. They do not "conflict" with a
    # 30-minute call in any way a person would recognise, so they are skipped
    # rather than treated as a 24-hour block that collides with everything.
    if "T" not in str(start_raw):
        return None
    try:
        start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return (start, end) if end > start else None


def _upcoming_events(session: Session, workspace_id: uuid.UUID, now: datetime, until: datetime):
    return session.execute(
        select(Signal, Connection)
        .join(Connection, Connection.id == Signal.connection_id)
        .where(
            Signal.workspace_id == workspace_id,
            Signal.type == SignalType.CALENDAR_EVENT,
            Signal.occurred_at >= now,
            Signal.occurred_at <= until,
            Connection.paused_at.is_(None),
        )
        .order_by(Signal.occurred_at.asc())
    ).all()


def _detect_meeting_conflicts(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """Two upcoming meetings on the same calendar that overlap in time.

    Double-booking is the clearest calendar fact there is: it needs no
    inference, only arithmetic on start and end, and only the person holding
    the calendar can resolve it. Grouped per connection deliberately - two
    different people being busy at the same time is not a conflict, and
    comparing across members would both invent one and cross the privacy
    boundary the rest of the system enforces.
    """
    rows = _upcoming_events(
        session, workspace_id, now, now + timedelta(days=MEETING_CONFLICT_HORIZON_DAYS)
    )

    by_connection: dict = {}
    for sig, conn in rows:
        window = _event_window(sig.payload or {})
        if window is None:
            continue
        by_connection.setdefault(conn.id, []).append((sig, conn, window[0], window[1]))

    candidates: list[dict] = []
    for events in by_connection.values():
        events.sort(key=lambda e: e[2])
        for i in range(len(events) - 1):
            sig_a, conn, start_a, end_a = events[i]
            sig_b, _, start_b, end_b = events[i + 1]
            if start_b >= end_a:
                continue
            overlap = int((min(end_a, end_b) - start_b).total_seconds() // 60)
            if overlap < 1:
                continue
            title_a = (sig_a.payload or {}).get("title") or "(no title)"
            title_b = (sig_b.payload or {}).get("title") or "(no title)"
            # Keyed on both events, sorted, so the pair produces exactly one
            # item and the key is stable whichever order they were read in.
            pair = ":".join(sorted([sig_a.external_id, sig_b.external_id]))
            candidates.append({
                "dedupe_key": f"meeting_conflict:{pair}",
                "connection_id": conn.id,
                "type": AttentionType.MEETING_CONFLICT,
                "source_provider": conn.provider.value,
                "title": f"Double-booked: {title_a} overlaps {title_b}",
                "why": f"{overlap} minute overlap on {start_b.strftime('%d %b')} - one of them needs moving",
                "evidence_url": (sig_b.payload or {}).get("url"),
                "priority": 0.72,
                "due_at": start_b,
            })
            if len(candidates) >= MEETING_CONFLICT_CAP:
                return candidates
    return candidates


def _detect_meeting_overload(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """A week that is mostly meetings.

    Aggregated to ONE item per calendar, like unanswered mail: listing every
    meeting would be exactly the noise this is meant to describe. Only the next
    seven days count - a crowded week you can no longer change is history
    rather than attention.
    """
    rows = _upcoming_events(session, workspace_id, now, now + timedelta(days=7))

    minutes: dict = {}
    counts: dict = {}
    conns: dict = {}
    for sig, conn in rows:
        window = _event_window(sig.payload or {})
        if window is None:
            continue
        start, end = window
        minutes[conn.id] = minutes.get(conn.id, 0.0) + (end - start).total_seconds() / 60
        counts[conn.id] = counts.get(conn.id, 0) + 1
        conns[conn.id] = conn

    candidates: list[dict] = []
    for connection_id, total in sorted(minutes.items(), key=lambda kv: -kv[1]):
        hours = total / 60
        if hours < MEETING_OVERLOAD_HOURS:
            continue
        candidates.append({
            "dedupe_key": f"meeting_overload:{connection_id}",
            "connection_id": connection_id,
            "type": AttentionType.MEETING_OVERLOAD,
            "source_provider": conns[connection_id].provider.value,
            "title": f"{round(hours)} hours of meetings in the next 7 days",
            "why": f"{counts[connection_id]} meetings booked - little room left for focused work",
            "evidence_url": None,
            "priority": 0.5,
        })
    return candidates


# --- engineering, deterministically ---------------------------------------
#
# These replace what the LangGraph engineering agent inferred behind an LLM
# call. The underlying facts - merge timestamps, requested reviewers, PR
# authors, changed directories - were always in the payloads; narrating them
# through a model added cost and a fresh duplicate row per run without adding
# information. See agents/engineering_agent.py for what is now retired.

PR_SLOW_MERGE_DAYS = 7
PR_SLOW_MERGE_CAP = 3
REVIEW_BOTTLENECK_MIN = 4  # open PRs on one reviewer before it counts as a queue
REVIEW_BOTTLENECK_CAP = 3
BUS_FACTOR_MIN_PRS = 5  # a directory needs real activity before it counts
BUS_FACTOR_CAP = 3
ISSUE_STALE_DAYS = 21
ISSUE_STALE_CAP = 5
ENGINEERING_LOOKBACK_DAYS = 30
DOC_STALE_DAYS = 90
DOC_STALE_CAP = 3


def _iso(value) -> datetime | None:
    """Parse an ISO timestamp from a payload, or None. Payload values are
    provider strings, so they are never trusted to parse."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _github_signals(session: Session, workspace_id: uuid.UUID, sig_type: SignalType, since: datetime):
    return session.execute(
        select(Signal, Connection)
        .join(Connection, Connection.id == Signal.connection_id)
        .where(
            Signal.workspace_id == workspace_id,
            Signal.type == sig_type,
            Signal.occurred_at >= since,
            Connection.provider == Provider.GITHUB,
            Connection.paused_at.is_(None),
        )
        .order_by(Signal.occurred_at.desc())
    ).all()


def _detect_slow_merges(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """Pull requests that took a long time to merge.

    Distinct from a stale PR, which is still open: this is about a repository
    whose merged work sat for a week first. The fact it reports is that the
    review pipeline is slow, not that any one PR needs action, so it is
    aggregated to one item per repository and uses the median rather than the
    worst case - one long-running PR is a story, not a pattern.
    """
    since = now - timedelta(days=ENGINEERING_LOOKBACK_DAYS)
    by_repo: dict = {}

    for sig, conn in _github_signals(session, workspace_id, SignalType.PR, since):
        payload = sig.payload or {}
        merged, created = _iso(payload.get("merged_at")), _iso(payload.get("created_at"))
        if merged is None or created is None:
            continue
        days = (merged - created).total_seconds() / 86400
        if days < 0:
            continue
        entry = by_repo.setdefault(conn.id, {"conn": conn, "days": [], "slow": 0})
        entry["days"].append(days)
        if days >= PR_SLOW_MERGE_DAYS:
            entry["slow"] += 1

    candidates: list[dict] = []
    for connection_id, entry in sorted(by_repo.items(), key=lambda kv: -kv[1]["slow"]):
        if not entry["days"] or entry["slow"] == 0:
            continue
        median = sorted(entry["days"])[len(entry["days"]) // 2]
        if median < PR_SLOW_MERGE_DAYS:
            continue
        slow, total = entry["slow"], len(entry["days"])
        candidates.append({
            "dedupe_key": f"pr_slow_merge:{connection_id}",
            "connection_id": connection_id,
            "type": AttentionType.PR_SLOW_MERGE,
            "source_provider": Provider.GITHUB.value,
            "title": f"Pull requests in {entry['conn'].full_name} take {round(median)} days to merge",
            "why": f"{slow} of {total} merged in the last {ENGINEERING_LOOKBACK_DAYS} days sat a week or more",
            "evidence_url": None,
            "priority": 0.5,
        })
        if len(candidates) >= PR_SLOW_MERGE_CAP:
            break
    return candidates


def _detect_review_bottleneck(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """One person carrying an unreviewed queue.

    Counts OPEN pull requests by requested reviewer. A queue is a fact about
    the present, so merged and closed PRs are excluded - a reviewer who
    cleared ten last week is not a bottleneck.
    """
    since = now - timedelta(days=ENGINEERING_LOOKBACK_DAYS)
    queues: dict = {}

    for sig, conn in _github_signals(session, workspace_id, SignalType.PR, since):
        payload = sig.payload or {}
        if payload.get("merged_at") or payload.get("closed_at"):
            continue
        for reviewer in payload.get("requested_reviewers") or []:
            entry = queues.setdefault((conn.id, reviewer), {"conn": conn, "prs": []})
            entry["prs"].append(payload)

    candidates: list[dict] = []
    for (connection_id, reviewer), entry in sorted(queues.items(), key=lambda kv: -len(kv[1]["prs"])):
        waiting = len(entry["prs"])
        if waiting < REVIEW_BOTTLENECK_MIN:
            continue
        candidates.append({
            "dedupe_key": f"review_bottleneck:{connection_id}:{reviewer}",
            "connection_id": connection_id,
            "type": AttentionType.REVIEW_BOTTLENECK,
            "source_provider": Provider.GITHUB.value,
            "title": f"{waiting} pull requests waiting on {reviewer}",
            "why": f"Review requests in {entry['conn'].full_name} are concentrated on one person",
            "evidence_url": (entry["prs"][0] or {}).get("url"),
            "priority": 0.6,
        })
        if len(candidates) >= REVIEW_BOTTLENECK_CAP:
            break
    return candidates


def _detect_bus_factor(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """A part of the codebase only one person ever touches.

    Built from the changed directories already recorded on each PR payload
    (`changed_dirs`, fetched at ingest and until now unused for anything but
    hotspot counting) crossed with PR authorship. Reported only where there
    has been real activity, so a directory touched twice by one person is not
    called a risk.
    """
    since = now - timedelta(days=ENGINEERING_LOOKBACK_DAYS)
    dirs: dict = {}

    for sig, conn in _github_signals(session, workspace_id, SignalType.PR, since):
        payload = sig.payload or {}
        author = payload.get("author") or sig.actor
        if not author:
            continue
        for directory in payload.get("changed_dirs") or []:
            entry = dirs.setdefault((conn.id, directory), {"conn": conn, "authors": {}})
            entry["authors"][author] = entry["authors"].get(author, 0) + 1

    candidates: list[dict] = []
    ranked = sorted(dirs.items(), key=lambda kv: -sum(kv[1]["authors"].values()))
    for (connection_id, directory), entry in ranked:
        total = sum(entry["authors"].values())
        if total < BUS_FACTOR_MIN_PRS or len(entry["authors"]) != 1:
            continue
        author = next(iter(entry["authors"]))
        candidates.append({
            "dedupe_key": f"bus_factor:{connection_id}:{directory}",
            "connection_id": connection_id,
            "type": AttentionType.BUS_FACTOR,
            "source_provider": Provider.GITHUB.value,
            "title": f"Only {author} has changed {directory}/ recently",
            "why": f"{total} pull requests touched it in {entry['conn'].full_name}, all by the same person",
            "evidence_url": None,
            "priority": 0.45,
        })
        if len(candidates) >= BUS_FACTOR_CAP:
            break
    return candidates


def _detect_stale_issues(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """Open issues nothing has happened to.

    Issues have been ingested since the GitHub module shipped and had no
    detector at all - the data was arriving, being stored, and never read.
    """
    cutoff = now - timedelta(days=ISSUE_STALE_DAYS)
    candidates: list[dict] = []

    for sig, conn in _github_signals(session, workspace_id, SignalType.ISSUE, now - timedelta(days=365)):
        payload = sig.payload or {}
        if payload.get("closed_at") or (payload.get("state") or "open") != "open":
            continue
        if sig.occurred_at > cutoff:
            continue
        age = _age_days(now, sig.occurred_at)
        candidates.append({
            "dedupe_key": f"issue_stale:{sig.external_id}",
            "connection_id": conn.id,
            "type": AttentionType.ISSUE_STALE,
            "source_provider": Provider.GITHUB.value,
            "title": payload.get("title") or f"Issue #{payload.get('number', '?')}",
            "why": f"Open {age} days with no movement - opened by {payload.get('author') or sig.actor}",
            "evidence_url": payload.get("url"),
            "priority": 0.4,
        })
        if len(candidates) >= ISSUE_STALE_CAP:
            break
    return candidates


def _detect_stale_documents(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    """Shared documents that have gone cold.

    Only SHARED files: a private working document going quiet is normal, while
    a shared one is something a team may still be relying on. Ownership comes
    from the signal's own `modified_by`, so the item names who last touched it
    rather than inventing an owner.
    """
    cutoff = now - timedelta(days=DOC_STALE_DAYS)
    rows = session.execute(
        select(Signal, Connection)
        .join(Connection, Connection.id == Signal.connection_id)
        .where(
            Signal.workspace_id == workspace_id,
            Signal.type == SignalType.DRIVE_FILE,
            Signal.occurred_at <= cutoff,
            Connection.paused_at.is_(None),
        )
        .order_by(Signal.occurred_at.asc())
    ).all()

    candidates: list[dict] = []
    for sig, conn in rows:
        payload = sig.payload or {}
        if not payload.get("shared"):
            continue
        age = _age_days(now, sig.occurred_at)
        owner = payload.get("modified_by") or sig.actor or "someone"
        name = payload.get("name") or "A shared document"
        candidates.append({
            "dedupe_key": f"doc_stale:{sig.external_id}",
            "connection_id": conn.id,
            "type": AttentionType.DOC_STALE,
            "source_provider": conn.provider.value,
            "title": f"{name} has not changed in {age} days",
            "why": f"Shared document, last edited by {owner} - it may be out of date",
            "evidence_url": payload.get("url"),
            "priority": 0.35,
        })
        if len(candidates) >= DOC_STALE_CAP:
            break
    return candidates


def _detect_findings(session: Session, workspace_id: uuid.UUID, now: datetime) -> list[dict]:
    since = now - timedelta(days=FINDING_LOOKBACK_DAYS)
    # Joined to the run so the finding carries the connection it was formed
    # about - the same link channel_briefing used to resolve separately, now
    # recorded once on the item like every other kind.
    findings = session.execute(
        select(AgentFinding, AgentRun.connection_id)
        .join(AgentRun, AgentRun.id == AgentFinding.run_id)
        .where(AgentFinding.workspace_id == workspace_id, AgentFinding.severity >= FINDING_MIN_SEVERITY, AgentFinding.created_at >= since)
        .order_by(AgentFinding.severity.desc())
    ).all()

    return [
        {
            "dedupe_key": f"finding:{f.id}",
            "connection_id": connection_id,
            "type": AttentionType.FINDING,
            "source_provider": "agent",
            "title": f.summary,
            "why": f"Flagged by the {f.agent} agent · severity {round(f.severity * 100)}%",
            "evidence_url": f"/findings/{f.id}",  # internal route - the finding detail page
            "priority": f.severity,
        }
        for f, connection_id in findings
    ]
