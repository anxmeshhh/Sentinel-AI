"""Sentinel's Microsoft 365 operations advisor.

The same interaction model as the Google and GitHub assistants - a prompt, a
visible trail, a grounded answer with sources - and built the same way: it reads
only what Sentinel has ALREADY ingested and analysed. It never calls Microsoft
Graph during a conversation. That is the product thesis applied to the
assistant: intelligence over data Sentinel already holds, not a second Graph
client that could contradict it.

Deterministic-first. Every number, conflict and ranking below is computed by
code; the model's only job is to read that state back operationally. It is
permanently scoped to the caller's own Microsoft workspace, so the user never
has to say "Microsoft" or "Outlook" - and neither should the answer.

Honesty is a feature here. Teams channel data requires a licensed Microsoft 365
work/school tenant; on a personal account Graph refuses it outright. The context
records that fact explicitly so the advisor can say so plainly instead of
implying the channels are simply quiet.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.llm import LLMClient, LLMError
from app.domain.finding import FindingTier
from app.models.connection import Connection, Provider
from app.models.signal import Signal, SignalType
from app.services.connection_state import connection_state
from app.services.findings import list_findings
from app.services.investigation import personal_scope
from app.services.situation_engine import list_situations

logger = structlog.get_logger("sentinel.microsoft_assistant")

MAIL_WINDOW_DAYS = 7
CALENDAR_HORIZON_DAYS = 14
# A conversation with at least this many messages in the window is "heating up".
# Deterministic, and deliberately low - three messages on one thread in a week is
# already a back-and-forth rather than an announcement.
BUSY_THREAD_MIN = 3

MICROSOFT_PROVIDERS = (
    Provider.MICROSOFT_OUTLOOK_MAIL,
    Provider.MICROSOFT_OUTLOOK_CALENDAR,
    Provider.MICROSOFT_TEAMS,
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse(raw) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return _aware(raw)
    try:
        return _aware(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
    except (ValueError, TypeError):
        return None


def _conflicts(events: list[dict]) -> list[dict]:
    """Overlapping meetings, computed - never left to the model, which reasons
    about times poorly. Two events conflict when one starts before the other
    ends. Reported once per pair."""
    dated = sorted(
        [e for e in events if e["start_dt"] and e["end_dt"]], key=lambda e: e["start_dt"]
    )
    out: list[dict] = []
    for i, a in enumerate(dated):
        for b in dated[i + 1:]:
            if b["start_dt"] >= a["end_dt"]:
                break  # sorted, so nothing later can overlap a either
            out.append({
                "a": a["title"], "b": b["title"],
                "when": a["start_dt"].strftime("%a %d %b %H:%M"),
            })
    return out


def microsoft_context(session: Session, workspace_id, user_id) -> dict:
    """Everything the advisor reasons over, gathered deterministically from the
    Sentinel pipeline - signals, findings and situations. No Graph calls."""
    now = datetime.now(timezone.utc)
    today = now.date()

    conns = session.execute(
        select(Connection).where(
            Connection.workspace_id == workspace_id,
            Connection.user_id == user_id,
            Connection.provider.in_(MICROSOFT_PROVIDERS),
        )
    ).scalars().all()
    by_provider: dict[Provider, list[Connection]] = {}
    for c in conns:
        by_provider.setdefault(c.provider, []).append(c)

    connected = bool(conns)
    mail_conns = by_provider.get(Provider.MICROSOFT_OUTLOOK_MAIL, [])
    cal_conns = by_provider.get(Provider.MICROSOFT_OUTLOOK_CALENDAR, [])
    teams_rows = by_provider.get(Provider.MICROSOFT_TEAMS, [])
    teams_channels = [c for c in teams_rows if c.repo]

    # --- Outlook Mail -----------------------------------------------------
    mail: dict = {
        "connected": bool(mail_conns),
        "state": connection_state(mail_conns[0]).value if mail_conns else None,
        "last_synced_at": mail_conns[0].last_synced_at if mail_conns else None,
        "total": 0, "attention": [], "today": [], "needs_reply": [], "busy_threads": [],
    }
    if mail_conns:
        rows = session.execute(
            select(Signal)
            .where(
                Signal.connection_id.in_([c.id for c in mail_conns]),
                Signal.type == SignalType.EMAIL,
                Signal.occurred_at >= now - timedelta(days=MAIL_WINDOW_DAYS),
            )
            .order_by(Signal.occurred_at.desc())
        ).scalars().all()
        mail["total"] = len(rows)

        threads: dict[str, list] = {}
        for s in rows:
            p = s.payload or {}
            labels = set(p.get("label_ids") or [])
            occurred = _aware(s.occurred_at)
            item = {
                "subject": p.get("subject") or "(no subject)",
                "from": p.get("from") or s.actor,
                "unread": "UNREAD" in labels,
                "important": "IMPORTANT" in labels or "STARRED" in labels,
                "bulk": bool(p.get("is_bulk")),
                "days_ago": (now - occurred).days,
                "at": occurred,
            }
            if item["unread"] and item["important"]:
                mail["attention"].append(item)
            if occurred.date() == today:
                mail["today"].append(item)
            # Sentinel does not track reply state; the honest, deterministic
            # proxy is "unread, addressed to you, and not bulk mail".
            if item["unread"] and not item["bulk"]:
                mail["needs_reply"].append(item)
            tid = p.get("thread_id")
            if tid:
                threads.setdefault(tid, []).append(item)

        for msgs in threads.values():
            if len(msgs) >= BUSY_THREAD_MIN:
                newest = max(msgs, key=lambda m: m["at"])
                mail["busy_threads"].append({
                    "subject": newest["subject"], "messages": len(msgs),
                    "days_ago": newest["days_ago"],
                })
        mail["busy_threads"].sort(key=lambda t: -t["messages"])
        for key in ("attention", "today", "needs_reply"):
            mail[key] = mail[key][:12]

    # --- Outlook Calendar -------------------------------------------------
    calendar: dict = {
        "connected": bool(cal_conns),
        "state": connection_state(cal_conns[0]).value if cal_conns else None,
        "today": [], "upcoming": [], "conflicts": [], "total": 0,
    }
    if cal_conns:
        rows = session.execute(
            select(Signal)
            .where(
                Signal.connection_id.in_([c.id for c in cal_conns]),
                Signal.type == SignalType.CALENDAR_EVENT,
                Signal.occurred_at >= now - timedelta(days=1),
                Signal.occurred_at <= now + timedelta(days=CALENDAR_HORIZON_DAYS),
            )
            .order_by(Signal.occurred_at.asc())
        ).scalars().all()
        events = []
        for s in rows:
            p = s.payload or {}
            start = _parse(p.get("start")) or _aware(s.occurred_at)
            events.append({
                "title": p.get("title") or "(no title)",
                "start_dt": start, "end_dt": _parse(p.get("end")),
                "when": start.strftime("%a %d %b %H:%M"),
                "attendees": int(p.get("attendee_count") or 0),
                "organizer": p.get("organizer"),
                "online": bool(p.get("has_meeting_link")),
                "status": p.get("status") or "confirmed",
                "hours_away": round((start - now).total_seconds() / 3600, 1),
            })
        calendar["total"] = len(events)
        calendar["today"] = [e for e in events if e["start_dt"].date() == today]
        calendar["upcoming"] = [e for e in events if e["start_dt"] >= now][:12]
        calendar["conflicts"] = _conflicts(events)

    # --- Teams ------------------------------------------------------------
    # Availability is reported honestly: a channel can be correctly monitored
    # while Graph refuses its messages (unlicensed account, or the protected
    # permission not granted). "No signals" and "not permitted" are different
    # answers and must never be conflated.
    teams: dict = {
        "connected": bool(teams_rows),
        "channels": [
            {
                "name": c.display_name or c.full_name,
                "priority": c.priority.value,
                "paused": c.paused_at is not None,
                "last_synced_at": c.last_synced_at,
                "messages_accessible": (c.last_sync_meta or {}).get("messages_accessible"),
            }
            for c in teams_channels
        ],
        "channel_count": len(teams_channels),
    }
    accessible_flags = [c["messages_accessible"] for c in teams["channels"]]
    teams["data_blocked"] = bool(accessible_flags) and all(f is False for f in accessible_flags)
    teams["never_synced"] = bool(teams_channels) and all(c["last_synced_at"] is None for c in teams["channels"])

    # --- Sentinel intelligence (findings + correlated situations) ---------
    scope = personal_scope(session, workspace_id, user_id)
    ms_provider_values = {p.value for p in MICROSOFT_PROVIDERS}
    all_findings = list_findings(session, scope)
    findings = [
        {
            "title": f.title, "why": f.summary, "tier": f.tier.value,
            "kind": f.kind, "provider": f.provider,
        }
        for f in all_findings
        if f.provider in ms_provider_values
    ][:12]
    critical = sum(1 for f in findings if f["tier"] == FindingTier.CRITICAL.value)

    situations = [
        {"title": s.title, "severity": s.severity, "members": s.member_count,
         "cross_provider": s.cross_provider}
        for s in list_situations(session, workspace_id, scope.key)
    ][:8]

    return {
        "connected": connected,
        "mail": mail,
        "calendar": calendar,
        "teams": teams,
        "findings": findings,
        "critical_findings": critical,
        "situations": situations,
    }


def _render_context(ctx: dict) -> str:
    lines: list[str] = []

    m = ctx["mail"]
    if not m["connected"]:
        lines.append("Mail: not connected.")
    else:
        synced = m["last_synced_at"].strftime("%d %b %H:%M") if m["last_synced_at"] else "never"
        lines.append(f"Mail (health {m['state']}, last synced {synced}): {m['total']} messages in the last {MAIL_WINDOW_DAYS} days.")
        if m["attention"]:
            lines.append("  Unread AND flagged important:")
            lines.extend(f"    - \"{i['subject']}\" from {i['from']} ({i['days_ago']}d ago)" for i in m["attention"])
        if m["today"]:
            lines.append(f"  Arrived today: {len(m['today'])}")
            lines.extend(f"    - \"{i['subject']}\" from {i['from']}" for i in m["today"][:8])
        if m["needs_reply"]:
            lines.append(f"  Unread and addressed to you (not bulk) - {len(m['needs_reply'])}:")
            lines.extend(f"    - \"{i['subject']}\" from {i['from']} ({i['days_ago']}d ago)" for i in m["needs_reply"][:8])
        if m["busy_threads"]:
            lines.append("  Conversations with sustained back-and-forth:")
            lines.extend(f"    - \"{t['subject']}\" — {t['messages']} messages, newest {t['days_ago']}d ago" for t in m["busy_threads"][:6])
        if m["total"] == 0:
            lines.append("  No messages have been ingested in this window.")

    c = ctx["calendar"]
    lines.append("")
    if not c["connected"]:
        lines.append("Calendar: not connected.")
    else:
        lines.append(f"Calendar (health {c['state']}): {c['total']} events from yesterday through the next {CALENDAR_HORIZON_DAYS} days.")
        if c["today"]:
            lines.append("  Today:")
            lines.extend(
                f"    - {e['when']} \"{e['title']}\" — {e['attendees']} attendees"
                f"{', online' if e['online'] else ''}{'' if e['status'] == 'confirmed' else ', ' + e['status']}"
                for e in c["today"]
            )
        else:
            lines.append("  Nothing scheduled today.")
        if c["upcoming"]:
            lines.append("  Upcoming:")
            lines.extend(f"    - {e['when']} \"{e['title']}\" — {e['attendees']} attendees ({e['hours_away']}h away)" for e in c["upcoming"][:8])
        if c["conflicts"]:
            lines.append("  Overlapping meetings (computed):")
            lines.extend(f"    - \"{x['a']}\" overlaps \"{x['b']}\" at {x['when']}" for x in c["conflicts"])
        else:
            lines.append("  No overlapping meetings detected.")

    t = ctx["teams"]
    lines.append("")
    if not t["connected"]:
        lines.append("Teams: not connected.")
    elif t["channel_count"] == 0:
        lines.append("Teams: connected, but no channels are being monitored yet.")
    else:
        lines.append(f"Teams: {t['channel_count']} channel(s) monitored.")
        for ch in t["channels"]:
            state = "paused" if ch["paused"] else "active"
            lines.append(f"    - {ch['name']} — priority {ch['priority']}, {state}")
        if t["data_blocked"]:
            lines.append(
                "  IMPORTANT: Microsoft is NOT returning channel data for this account. "
                "Teams channel messages require a licensed Microsoft 365 work or school tenant; "
                "this account is not one, so there is no channel activity to report - "
                "this is a licensing/permission limit, NOT a quiet channel."
            )
        elif t["never_synced"]:
            lines.append("  These channels have not synced yet, so there is no activity to report.")

    lines.append("")
    if ctx["findings"]:
        lines.append(f"Findings Sentinel has already detected here ({ctx['critical_findings']} critical):")
        lines.extend(f"    - [{f['tier']}] {f['title']} — {f['why']}" for f in ctx["findings"])
    else:
        lines.append("Sentinel has detected no findings in this workspace yet.")

    if ctx["situations"]:
        lines.append("")
        lines.append("Correlated situations (several findings about one thing):")
        lines.extend(
            f"    - {s['title']} — {s['severity']}, {s['members']} findings"
            f"{', spans providers' if s['cross_provider'] else ''}"
            for s in ctx["situations"]
        )

    return "\n".join(lines)


_SYSTEM = """You are Sentinel's operations advisor for this user's connected \
Microsoft 365 workspace. Sentinel has already ingested and analysed it; the \
current state is given below. You are permanently scoped to THIS workspace, so \
never ask the user to name an account and never say "Microsoft", "Outlook" or \
"your Microsoft workspace" unnecessarily - they know. Just answer about their \
mail, calendar and channels directly.

Rules:
- Ground every statement in the state below. Never invent an email, meeting, \
channel, attendee or finding. If something is not in the state, say it is not \
there.
- The state is what Sentinel has SYNCED. If a section is empty, say plainly \
that nothing has been synced or nothing is there - never imply you looked \
somewhere else, and never guess at what might exist.
- If the state says Microsoft is not returning Teams channel data because the \
account is not a licensed work or school tenant, say exactly that when asked \
about channels. Do NOT describe those channels as quiet, inactive or healthy - \
that would be a false reading of a permission limit.
- Sentinel tracks message metadata (subject, sender, unread/important flags, \
conversation grouping) - never message bodies. It does not track whether a \
message was replied to; "may need a reply" means unread and addressed to them \
directly. Say so if it matters.
- Overlapping meetings and all counts are already computed - use them, do not \
recompute or estimate times yourself.
- Lead with what needs attention, then what is merely notable. Be concise and \
operational - a short paragraph or a few bullets, a briefing not an essay. \
Answer only what was asked."""


def _sources(ctx: dict) -> list[dict]:
    """What the advisor reasoned over, made navigable - the same way the Google
    and GitHub assistants cite their inputs."""
    out: list[dict] = []
    m, c, t = ctx["mail"], ctx["calendar"], ctx["teams"]
    if m["connected"]:
        out.append({
            "kind": "mail", "title": "Mail",
            "meta": f"{m['total']} messages · {len(m['attention'])} need attention", "url": None,
        })
    if c["connected"]:
        out.append({
            "kind": "calendar", "title": "Calendar",
            "meta": f"{len(c['today'])} today · {len(c['conflicts'])} overlaps", "url": None,
        })
    for ch in t["channels"][:4]:
        blocked = ch["messages_accessible"] is False
        out.append({
            "kind": "channel", "title": ch["name"],
            "meta": "channel data unavailable for this account" if blocked else f"priority {ch['priority']}",
            "url": None,
        })
    for f in ctx["findings"][:4]:
        out.append({"kind": "finding", "title": f["title"], "meta": f["tier"], "url": None})
    return out


def answer_microsoft_stream(session: Session, workspace_id, user_id, question: str) -> Iterator[dict]:
    """Yield the same event shape the Google and GitHub streams use: real status
    steps as they happen, then one result with the answer and its sources."""
    yield {"type": "status", "message": "Reading your mail and calendar…"}
    ctx = microsoft_context(session, workspace_id, user_id)

    if not ctx["connected"]:
        yield {
            "type": "result", "status": "done",
            "reply": "Microsoft 365 isn't connected yet. Connect it from the connection page and I can start advising on your mail, calendar and channels.",
            "sources": [],
        }
        return

    yield {"type": "status", "message": "Reviewing findings and situations…"}
    prompt = f"{_render_context(ctx)}\n\nQuestion: {question}"
    try:
        reply = LLMClient().complete_text(system=_SYSTEM, messages=[{"role": "user", "content": prompt}])
    except LLMError as exc:
        logger.warning("microsoft_assistant_llm_failed", error=str(exc)[:200])
        yield {
            "type": "result", "status": "error",
            "reply": "Sentinel couldn't complete that just now. Nothing was changed.",
            "sources": [],
        }
        return

    yield {"type": "result", "status": "done", "reply": reply, "sources": _sources(ctx)}
