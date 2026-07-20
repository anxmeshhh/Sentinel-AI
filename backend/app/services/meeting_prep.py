"""Phase 2u: "Prepare Me" - a structured meeting brief.

## Why this isn't just an orchestrator prompt

The AI Command orchestrator can already answer "prepare me for my next
meeting" - it chains calendar → email → drive → history and produces a good
brief. But it re-derives *how* to do that on every request, costing ~7
sequential LLM round-trips (~20-30k tokens). Against this project's real
200k/day ceiling that is roughly seven briefs per day, and the plan varies
run to run.

Meeting prep is a *known shape*, so it doesn't need a model to discover it:

    the meeting        -> already in the database, free
    attendee emails    -> a precise Gmail query on their real addresses
    related documents  -> a Drive query on meaningful title keywords
    prior meetings     -> same attendees or same title, from local Signals

Retrieval is deterministic; the LLM is used **once**, to synthesize. That is
this codebase's standard pattern ("detection is deterministic, the LLM
narrates") - the orchestrator is the deliberate exception, and a known goal
shape shouldn't pay exception prices.

The orchestrator is *not* replaced: open-ended questions ("which documents
mention X") still belong to it. Two retrieval strategies, one intelligence
architecture.

## Progressive retrieval

Skips are enforced here in code, not suggested in a prompt:

- no attendees        -> skip the email and prior-meeting searches entirely
                         (a solo focus block has nobody to search for)
- generic title       -> skip Drive ("Meeting", "Sync", "1:1" as a search
                         query returns noise, and noise costs tokens)
- nothing found       -> return a minimal brief with **zero** LLM calls

Every retrieval is independently guarded: one failing source degrades the
brief, it never fails it.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.llm import LLMClient, LLMError
from app.integrations.gmail_client import GmailClient
from app.integrations.google_auth import get_valid_access_token
from app.integrations.google_drive_client import GoogleDriveClient
from app.models.connection import Provider
from app.models.meeting_brief import MeetingBrief
from app.models.signal import Signal, SignalType
from app.services.drive_query import build_drive_query

logger = structlog.get_logger("sentinel.meeting_prep")

EMAIL_LOOKBACK_DAYS = 21
MAX_EMAILS = 5
MAX_DOCUMENTS = 3
MAX_PRIOR_MEETINGS = 2
MAX_ATTENDEES_IN_QUERY = 5  # a 40-person invite would build an absurd query string

# Titles that carry no searchable meaning. Searching Drive for "Sync"
# returns whatever happens to contain that word - noise the user pays for
# in tokens and reads as irrelevant.
GENERIC_TITLE_WORDS = {
    "meeting", "sync", "standup", "stand-up", "call", "catchup", "catch-up", "check-in",
    "checkin", "1:1", "one-on-one", "weekly", "daily", "monthly", "review", "chat",
    "discussion", "session", "hold", "block", "focus", "busy", "reminder", "appointment",
}
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'&.-]*")


@dataclass
class BriefSources:
    emails: list[dict] = field(default_factory=list)
    documents: list[dict] = field(default_factory=list)
    prior_meetings: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.emails or self.documents or self.prior_meetings)


def meaningful_keywords(title: str) -> list[str]:
    """Words worth searching for. A title made only of generic scheduling
    vocabulary yields nothing, which is the signal to skip Drive."""
    words = _WORD_RE.findall(title or "")
    return [w for w in words if _is_searchable(w) and w.lower() not in GENERIC_TITLE_WORDS]


def _is_searchable(word: str) -> bool:
    """Length alone is the wrong test: it throws away exactly the short
    tokens that carry the most meaning in a work title - "Q3", "AI", "UX",
    "v2" - while a plain length cutoff exists only to drop filler like
    "of"/"to"/"at". So: keep anything longer than two characters, anything
    containing a digit, and any all-caps acronym."""
    # A bare short number is never a useful search term - it's the debris
    # left by titles like "1:1" or "Q1 vs Q2" once they're tokenized. A
    # longer one ("2026") still is.
    if word.isdigit():
        return len(word) >= 4
    if len(word) > 2:
        return True
    return any(c.isdigit() for c in word) or word.isupper()


def get_cached_brief(session: Session, workspace_id: uuid.UUID, event_external_id: str) -> MeetingBrief | None:
    return session.execute(
        select(MeetingBrief).where(
            MeetingBrief.workspace_id == workspace_id, MeetingBrief.event_external_id == event_external_id
        )
    ).scalar_one_or_none()


def prepare_meeting(
    session: Session,
    workspace_id: uuid.UUID,
    event: Signal,
    *,
    team_id: uuid.UUID | None = None,
    refresh: bool = False,
) -> MeetingBrief:
    """Build (or return the cached) brief for `event`.

    `team_id` scopes retrieval to a Channel's authorized Connections, reusing
    the orchestrator's existing gate - so a brief requested inside a channel
    can never read a connection that channel wasn't given.
    """
    if not refresh:
        cached = get_cached_brief(session, workspace_id, event.external_id)
        if cached is not None:
            return cached

    title = event.payload.get("title") or "Untitled meeting"
    attendees = [a for a in (event.payload.get("attendee_emails") or []) if a]
    keywords = meaningful_keywords(title)

    sources = BriefSources()
    if attendees:
        sources.emails = _find_attendee_emails(session, workspace_id, attendees, team_id=team_id)
        sources.prior_meetings = _find_prior_meetings(session, workspace_id, event, attendees)
    if keywords:
        sources.documents = _find_related_documents(session, workspace_id, keywords, team_id=team_id)

    narrative, prep_points = _synthesize(title, event, attendees, sources)

    brief = get_cached_brief(session, workspace_id, event.external_id)
    if brief is None:
        brief = MeetingBrief(workspace_id=workspace_id, event_external_id=event.external_id, title=title, narrative="", prep_points=[], sources=[])
        session.add(brief)
    brief.title = title
    brief.narrative = narrative
    brief.prep_points = prep_points
    brief.sources = _flatten_sources(event, sources)
    session.commit()
    session.refresh(brief)

    logger.info(
        "meeting_brief_built",
        # NOT `event=` - structlog reserves that name for the log message
        # itself, and passing it as a kwarg raises at runtime.
        workspace_id=str(workspace_id), event_id=event.external_id,
        emails=len(sources.emails), documents=len(sources.documents), prior=len(sources.prior_meetings),
    )
    return brief


def _local_signals(session: Session, workspace_id: uuid.UUID, signal_type: SignalType) -> list[Signal]:
    return list(
        session.execute(
            select(Signal).where(Signal.workspace_id == workspace_id, Signal.type == signal_type)
        ).scalars()
    )


def _is_demo(session: Session, workspace_id: uuid.UUID) -> bool:
    from app.models.workspace import Workspace

    workspace = session.get(Workspace, workspace_id)
    return bool(workspace and workspace.is_demo)


def _find_attendee_emails(session: Session, workspace_id: uuid.UUID, attendees: list[str], *, team_id: uuid.UUID | None) -> list[dict]:
    """Search by the attendees' real addresses - far more precise than
    guessing keywords from a meeting title, and it's the thing a human would
    actually do before a meeting."""
    from app.services.orchestrator import _get_connection

    people = attendees[:MAX_ATTENDEES_IN_QUERY]

    if _is_demo(session, workspace_id):
        results = []
        for s in _local_signals(session, workspace_id, SignalType.EMAIL):
            sender = (s.payload.get("from") or "").lower()
            if any(p.lower() in sender for p in people):
                results.append(
                    {
                        "subject": s.payload.get("subject") or "(no subject)",
                        "from": s.payload.get("from"),
                        "url": f"https://mail.google.com/mail/u/0/#all/{s.external_id}",
                        "occurred_at": s.occurred_at.isoformat(),
                    }
                )
        return results[:MAX_EMAILS]

    connection = _get_connection(session, workspace_id, team_id, Provider.GMAIL)
    if connection is None:
        return []

    since = (datetime.now(timezone.utc) - timedelta(days=EMAIL_LOOKBACK_DAYS)).strftime("%Y/%m/%d")
    query = f"from:({' OR '.join(people)}) after:{since}"
    try:
        access_token = get_valid_access_token(session, connection)
        with GmailClient(access_token) as client:
            messages = client.search(query, max_results=MAX_EMAILS)
    except Exception as exc:  # one dead source degrades the brief, never fails it
        logger.warning("meeting_prep_email_search_failed", error=str(exc))
        return []

    return [
        {
            "subject": m["payload"]["subject"],
            "from": m["payload"]["from"],
            "url": f"https://mail.google.com/mail/u/0/#all/{m['external_id']}",
            "occurred_at": m["occurred_at"].isoformat(),
        }
        for m in messages
    ]


def _find_related_documents(session: Session, workspace_id: uuid.UUID, keywords: list[str], *, team_id: uuid.UUID | None) -> list[dict]:
    from app.services.orchestrator import _get_connection

    query_terms = " ".join(keywords[:4])

    if _is_demo(session, workspace_id):
        results = []
        for s in _local_signals(session, workspace_id, SignalType.DRIVE_FILE):
            haystack = f"{s.payload.get('name', '')} {s.payload.get('content', '')}".lower()
            if any(k.lower() in haystack for k in keywords):
                results.append({"name": s.payload.get("name"), "url": s.payload.get("url"), "modified_at": s.occurred_at.isoformat()})
        return results[:MAX_DOCUMENTS]

    connection = _get_connection(session, workspace_id, team_id, Provider.GOOGLE_DRIVE)
    if connection is None:
        return []

    try:
        access_token = get_valid_access_token(session, connection)
        with GoogleDriveClient(access_token) as client:
            files = client.search(build_drive_query(keywords=query_terms), max_results=MAX_DOCUMENTS)
    except Exception as exc:
        logger.warning("meeting_prep_drive_search_failed", error=str(exc))
        return []

    return [{"name": f["name"], "url": f.get("url"), "modified_at": f.get("modified_at")} for f in files]


def _find_prior_meetings(session: Session, workspace_id: uuid.UUID, event: Signal, attendees: list[str]) -> list[dict]:
    """Local Signals only - no API call, so this costs nothing. Matches on
    shared attendees or an identical title."""
    now = datetime.now(timezone.utc)
    attendee_set = {a.lower() for a in attendees}
    title = (event.payload.get("title") or "").strip().lower()

    candidates = []
    for s in _local_signals(session, workspace_id, SignalType.CALENDAR_EVENT):
        if s.external_id == event.external_id or s.payload.get("status") == "cancelled":
            continue
        try:
            start = datetime.fromisoformat(s.payload.get("start") or "")
        except ValueError:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if start >= now:  # prior meetings only
            continue

        others = {a.lower() for a in (s.payload.get("attendee_emails") or [])}
        same_title = (s.payload.get("title") or "").strip().lower() == title and title != ""
        if not (attendee_set & others or same_title):
            continue
        candidates.append(
            {"title": s.payload.get("title"), "start": start.isoformat(), "url": s.payload.get("url"), "_sort": start}
        )

    candidates.sort(key=lambda c: c["_sort"], reverse=True)
    for c in candidates:
        c.pop("_sort", None)
    return candidates[:MAX_PRIOR_MEETINGS]


def _synthesize(title: str, event: Signal, attendees: list[str], sources: BriefSources) -> tuple[str, list[str]]:
    """The one LLM call in this workflow - and it's skipped entirely when
    there's nothing to synthesize."""
    when = event.payload.get("start")

    if sources.is_empty():
        # No context found. An LLM call here could only produce filler, and
        # filler that looks like insight is worse than an honest blank.
        who = f" with {len(attendees)} attendee{'s' if len(attendees) != 1 else ''}" if attendees else ""
        return (
            f"No related emails, documents or previous meetings were found for “{title}”{who}. "
            "Nothing to review beforehand from your connected tools.",
            [],
        )

    facts = {
        "meeting": {"title": title, "start": when, "attendees": attendees[:MAX_ATTENDEES_IN_QUERY]},
        "recent_emails_from_attendees": [{"subject": e["subject"], "from": e["from"]} for e in sources.emails],
        "related_documents": [d["name"] for d in sources.documents],
        "previous_meetings": [{"title": m["title"], "when": m["start"]} for m in sources.prior_meetings],
    }

    try:
        result = LLMClient().complete_json(
            system=(
                "You are Sentinel, preparing someone for a meeting. Using ONLY the provided data, write a "
                "brief. STRICT RULES: never invent a person, document, subject or fact that is not in the "
                "data; if something is absent, say nothing about it rather than guessing. "
                "'narrative' = at most 3 short sentences on what this meeting is about and what context "
                "matters. 'prep_points' = up to 4 short, concrete things to do or be ready for, each "
                "grounded in the data. Plain text, no markdown. "
                'Return JSON: {"narrative": "...", "prep_points": ["...", "..."]}'
            ),
            user=str(facts),
        )
        narrative = (result.get("narrative") or "").strip()
        points = [str(p).strip() for p in (result.get("prep_points") or []) if str(p).strip()][:4]
        if narrative:
            return narrative, points
    except LLMError:
        logger.warning("meeting_prep_llm_unavailable_using_fallback")

    # Deterministic fallback: the facts still reach the user, just without
    # the synthesis. Degrades in polish, never in correctness.
    bits = []
    if sources.emails:
        bits.append(f"{len(sources.emails)} recent email{'s' if len(sources.emails) != 1 else ''} from attendees")
    if sources.documents:
        bits.append(f"{len(sources.documents)} related document{'s' if len(sources.documents) != 1 else ''}")
    if sources.prior_meetings:
        bits.append(f"{len(sources.prior_meetings)} previous meeting{'s' if len(sources.prior_meetings) != 1 else ''}")
    return f"Found {', '.join(bits)} for “{title}”. Review the linked sources below.", []


def _flatten_sources(event: Signal, sources: BriefSources) -> list[dict]:
    flat = [{"kind": "meeting", "label": event.payload.get("title") or "Meeting", "url": event.payload.get("url")}]
    flat += [{"kind": "email", "label": e["subject"], "url": e["url"]} for e in sources.emails]
    flat += [{"kind": "document", "label": d["name"], "url": d["url"]} for d in sources.documents]
    flat += [{"kind": "prior_meeting", "label": m["title"], "url": m["url"]} for m in sources.prior_meetings]
    return flat
