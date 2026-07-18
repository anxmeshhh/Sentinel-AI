"""AI Command orchestrator - the tool-calling agent loop behind a Connection
Workspace's "Unified AI Interface" (currently wired for Google only; see
PHASES.md's staging note on generalizing to other providers later).

This is deliberately different from every other agent in the codebase.
Engineering/Communication/Executive all follow "detection is deterministic
Python, the LLM only narrates a candidate that already exists" - their job
is to describe something already computed. This module's whole point is the
opposite: the model decides, step by step, which real tools to call and in
what order to answer a free-form request that might span multiple services
("summarize my important emails and check my calendar for conflicts").

Safety model - this is the part that actually matters:
- Read tools (search_emails, read_email_body, list_calendar_events) execute
  immediately and automatically inside the loop. They can't change anything.
- Write tools (create_calendar_event) NEVER execute automatically. The
  moment the model calls one, the loop stops and returns a human-readable
  plan instead of a result. Nothing happens to the user's actual calendar
  until execute_planned_action() is called separately, from a route that
  only fires when the user clicks "Confirm & Execute" in the UI - and even
  then it re-validates workspace ownership before touching anything.
- MAX_STEPS bounds the loop so a confused model can't spin forever burning
  tool calls.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.llm import LLMClient, LLMError, LLMOverloadedError
from app.integrations.gmail_client import GmailClient
from app.integrations.google_auth import get_valid_access_token
from app.integrations.google_calendar_client import GoogleCalendarClient
from app.integrations.google_drive_client import GoogleDriveClient
from app.models.channel_ai_history import ChannelAIHistoryEntry
from app.models.channel_connection import ChannelConnection
from app.models.connection import Connection, Provider
from app.repositories.connections import ConnectionRepository
from app.services.calendar_query import find_free_slots, list_calendar, list_calendar_range
from app.services.channel_connections import is_resource_allowed, list_channel_connections
from app.services.drive_query import build_drive_query
from app.services.holiday_query import list_indian_holidays
from app.services.ingestion import ingest_connection
from app.services.mail_query import build_gmail_query
from app.services.meet_query import list_meetings, meeting_status

logger = structlog.get_logger("sentinel.orchestrator")

MAX_STEPS = 10  # composite workflows (meeting prep, cross-document search) chain more tools than a single lookup
WRITE_TOOLS = {"create_calendar_event"}

# Which Connection a tool needs - used only when a Channel scopes the
# request (Phase 2m). Read tools built on ingested Signal data
# (list_calendar_events, find_free_slot, list_meeting_history, get_holidays)
# have no per-item "resource" of their own to allow-list against (unlike a
# specific Drive file or GitHub repo) - gating them at the
# connection-assignment level is as far as enforcement honestly goes today;
# see PHASES.md's Phase 2m notes for why finer-grained calendar/email
# resource permissions aren't built.
TOOL_PROVIDERS = {
    "search_emails": Provider.GMAIL,
    "read_email_body": Provider.GMAIL,
    "list_calendar_events": Provider.GOOGLE_CALENDAR,
    "find_free_slot": Provider.GOOGLE_CALENDAR,
    "get_holidays": Provider.GOOGLE_CALENDAR,
    "create_calendar_event": Provider.GOOGLE_CALENDAR,
    "list_meeting_history": Provider.GOOGLE_CALENDAR,
    "search_drive": Provider.GOOGLE_DRIVE,
    "read_drive_file": Provider.GOOGLE_DRIVE,
}


def _system_prompt() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d (%A)")
    return f"""You are Sentinel's AI Command interface for a user's connected Google \
services (Gmail, Calendar, Drive, Meet). Today's date is {today} (UTC) - resolve relative dates \
("today", "yesterday", "this week", "tomorrow afternoon") to real dates yourself before calling a \
tool; tools only accept explicit dates, not relative phrases.

You have tools to search Gmail (live, whole-mailbox search), read one specific email's full \
content, list calendar events, list past/upcoming Meet meetings, search Google Drive, read one \
specific Drive file's actual content, look up Indian public holidays/festivals, and create a new \
calendar event (optionally with a Google Meet link). Use tools to gather whatever real information \
you actually need before answering - never invent an email, event, file, meeting, holiday date, \
person, or detail that a tool didn't return. For search_emails/search_drive, extract real \
structured parameters from the request (keywords/topic, sender, a label or type filter, a date \
range) rather than guessing - e.g. "any important emails from Unstop" means sender="unstop", \
label_filter="important", not a bare keyword search for the word "important".

Composite requests should chain whatever tools the request actually needs, combining results in \
one answer:
- "Find the presentation for tomorrow's meeting" = list_calendar_events + search_drive.
- "Prepare me for tomorrow's client meeting" = list_calendar_events (find it) + search_emails \
(recent messages from the attendees/about the topic) + search_drive (related documents) + \
list_meeting_history (past meetings with the same people/topic) - combine into a short meeting \
brief: objective, relevant documents, recent email context, prior meeting context, suggested prep.
- "Summarize this document" / "extract deadlines" / "what does this say about X" = search_drive to \
find the file (if not already identified), then read_drive_file for its actual content - never \
answer content questions from the file name alone.
- "Compare document A with document B" = read_drive_file on both, then describe concrete \
differences grounded in what each file actually contains.
- "Which documents mention X" = search_drive with keywords, then read_drive_file on each strong \
candidate (only as many as actually needed) to confirm/quote the real mention - don't guess from \
titles alone.
- If a document's content reveals a real deadline the user might want on their calendar, mention it \
and offer to add it - only call create_calendar_event if the user confirms they want that.
get_holidays returns real dates from Google's own Indian holiday calendar - always call it rather \
than answering a holiday-date question from memory, since exact dates (especially lunar-calendar \
festivals like Diwali/Eid/Holi) shift every year.

Every email, event, meeting, and file a tool returns includes a real "url" field (or "calendar_url"/\
"meet_url" for meetings) - Sentinel never opens or renders these resources itself, it only links \
out to the real Gmail/Calendar/Drive/Meet page. Whenever you mention a specific resource in your \
answer, include it as a real markdown link using that exact url, e.g. [Sprint Sync](url) or \
[Q3 Report.pdf](url) - never write a bare resource name with no link, and never invent a url that \
didn't come from a tool.

If the request requires creating or changing something (like scheduling a meeting), call \
create_calendar_event as soon as you have enough information - it will not actually run until \
the user confirms it themselves, so you don't need to ask permission first, just propose the \
concrete action. But only call it when the user actually asked to create/schedule/book \
something - "find a free slot" means report the slot and stop, not schedule anything into it \
unless asked. Keep your final answer concise and grounded only in what the tools returned.

Formatting: you're writing for a narrow chat panel, not a document. Never use markdown tables \
(pipe characters) - they don't fit and render unreadably, even for a "compare A vs B" answer - use \
short bulleted "A: ..." / "B: ..." pairs per aspect instead of a table. For a list of emails, \
events, meetings, or files, use a short numbered or bulleted list instead, one item per line, with \
just the essentials (the linked name, and the one detail that matters most) - not a dump of every \
field a tool returned.

Be efficient with tool calls - each one costs real time and a real API rate-limit budget shared \
across the whole request. Don't repeat a search with only a minor variation (a slightly different \
keyword, or a date range shifted by a day) if the previous call already returned enough to work \
with - move to synthesizing an answer once you have "enough", not "everything possible". For a \
composite request like meeting prep, one search_emails call and one search_drive call (broad \
enough to catch relevant results) is normally sufficient - don't re-run the same tool 3+ times \
chasing a better query."""


@dataclass
class OrchestrationResult:
    status: str  # "done" | "confirmation_required" | "error"
    reply: str | None = None
    plan: dict | None = None
    pending_action: dict | None = None
    steps: list[dict] = field(default_factory=list)


def _tool_schemas(allowed_providers: set[Provider] | None = None) -> list[dict]:
    """`allowed_providers=None` means the plain, workspace-wide AI Command
    (every tool offered, unchanged from before Phase 2m). A Channel-scoped
    request passes the actual set of providers assigned to that Channel -
    only those tools are ever offered to the model, so it can't reach a
    connection the Channel was never given access to in the first place.
    """
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "search_emails",
                "description": (
                    "Live search across the user's whole Gmail account using Gmail's own search index - "
                    "not limited to a small recently-synced cache. Returns metadata only (subject, sender, "
                    "date, labels), never message bodies. All parameters are optional; combine whichever "
                    "apply to the request."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keywords": {"type": "string", "description": "Topic/keyword search, e.g. 'hackathon'. Omit if not topic-specific."},
                        "sender": {"type": "string", "description": "Sender name, email, or domain, e.g. 'unstop' or 'unstop.com'."},
                        "label_filter": {"type": "string", "enum": ["starred", "important", "unread", "spam"]},
                        "since": {"type": "string", "description": "ISO date YYYY-MM-DD - only emails on/after this date."},
                        "until": {"type": "string", "description": "ISO date YYYY-MM-DD - only emails before this date."},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_email_body",
                "description": "Fetch one specific email's full content by its message id (the 'id' field from search_emails results). Live fetch, never stored.",
                "parameters": {
                    "type": "object",
                    "properties": {"message_id": {"type": "string"}},
                    "required": ["message_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_calendar_events",
                "description": (
                    "List the user's calendar events. Either give a simple range (upcoming/past), or an "
                    "explicit since/until date range for a specific day or period (e.g. 'today', 'this week')."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "range": {"type": "string", "enum": ["upcoming", "past"], "description": "Omit if using since/until instead."},
                        "since": {"type": "string", "description": "ISO datetime - start of an explicit range."},
                        "until": {"type": "string", "description": "ISO datetime - end of an explicit range."},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_free_slot",
                "description": (
                    "Find real gaps between existing events on one day, computed deterministically from the "
                    "actual calendar - use this instead of guessing when asked to find a free slot or schedule "
                    "something 'whenever works'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                        "start_hour": {"type": "integer", "default": 9, "description": "24h clock, e.g. 12 for 'afternoon' start"},
                        "end_hour": {"type": "integer", "default": 18, "description": "24h clock, e.g. 18 for end of workday"},
                        "duration_minutes": {"type": "integer", "default": 30},
                    },
                    "required": ["date"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_drive",
                "description": (
                    "Live search across the user's Google Drive using Drive's own search index - file/doc "
                    "name and content, not a local cache. Returns metadata + a link to open in Drive, never "
                    "file content itself."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keywords": {"type": "string", "description": "Topic/keyword/filename search, e.g. 'Sentinel project'."},
                        "mime_type": {"type": "string", "enum": ["pdf", "document", "spreadsheet", "presentation", "folder"]},
                        "modified_after": {"type": "string", "description": "ISO date YYYY-MM-DD - only files modified on/after this date."},
                        "shared_with_me": {"type": "boolean", "default": False},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_drive_file",
                "description": (
                    "Read one specific Drive file's actual content by its id (the 'id' field from "
                    "search_drive results) - live fetch, never stored. Required before answering any "
                    "question about what a document actually says (summarize, extract deadlines/action "
                    "items, compare, confirm a mention) - never answer from the filename alone. Only "
                    "Docs/Sheets/Slides/PDF/Word/plain-text files can be read; other types return an error."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"file_id": {"type": "string"}},
                    "required": ["file_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_meeting_history",
                "description": "List past or upcoming meetings (calendar events with a Google Meet link) - use for meeting-prep requests that need prior meeting context.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "range": {"type": "string", "enum": ["upcoming", "past"]},
                        "search": {"type": "string", "description": "Optional keyword filter on the meeting title."},
                    },
                    "required": ["range"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_holidays",
                "description": (
                    "Real Indian public holidays/festivals for a date range, from Google's own Indian "
                    "holiday calendar - always real dates for the actual year asked about, never guessed. "
                    "Each result has a category: national, regional, festival, or observance."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "since": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                        "until": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                        "state": {"type": "string", "description": "Indian state name, to filter regional holidays to just that state. Omit for all."},
                    },
                    "required": ["since", "until"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_calendar_event",
                "description": (
                    "Create a new calendar event, optionally with a Google Meet link. "
                    "WRITE ACTION - will be shown to the user for confirmation, not executed immediately."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start": {"type": "string", "description": "ISO 8601 datetime, e.g. 2026-07-19T15:00:00+00:00"},
                        "end": {"type": "string", "description": "ISO 8601 datetime"},
                        "attendee_emails": {"type": "array", "items": {"type": "string"}},
                        "create_meet_link": {"type": "boolean", "default": False},
                    },
                    "required": ["title", "start", "end"],
                },
            },
        },
    ]
    if allowed_providers is None:
        return schemas
    return [s for s in schemas if TOOL_PROVIDERS.get(s["function"]["name"]) in allowed_providers]


STATUS_MESSAGES = {
    "search_emails": "Searching your emails…",
    "read_email_body": "Reading an email…",
    "list_calendar_events": "Checking your calendar…",
    "find_free_slot": "Looking for a free slot…",
    "search_drive": "Searching your Drive…",
    "get_holidays": "Checking Indian holidays…",
    "read_drive_file": "Reading a file…",
    "list_meeting_history": "Checking meeting history…",
}


def run_command(
    session: Session, workspace_id: uuid.UUID, user_command: str, *, team_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None
) -> OrchestrationResult:
    """Non-streaming form - drains run_command_stream and returns just the
    final result. Kept for callers that don't need live progress (tests,
    the Assistant's simpler needs) so the loop logic lives in exactly one place.
    """
    final: dict = {}
    for event in run_command_stream(session, workspace_id, user_command, team_id=team_id, user_id=user_id):
        if event["type"] == "result":
            final = event
    return OrchestrationResult(
        status=final.get("status", "error"),
        reply=final.get("reply"),
        plan=final.get("plan"),
        pending_action=final.get("pending_action"),
        steps=final.get("steps", []),
    )


def run_command_stream(
    session: Session, workspace_id: uuid.UUID, user_command: str, *, team_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None
):
    """Generator form - yields real progress as each tool call actually
    happens, so the UI can show what's genuinely occurring instead of a
    frozen spinner. Two event shapes:
    - {"type": "status", "message": str} - a step just started
    - {"type": "result", "status": ..., ...} - the final (and only) result, always last

    `team_id` (Phase 2m) scopes this to one Channel: only tools backed by a
    Connection actually assigned to that Channel are ever offered to the
    model, and Drive file reads are additionally checked against that
    Channel's resource allow-list. `team_id=None` (the original, still-used
    plain workspace-wide Google AI Command) behaves exactly as before this
    phase - every tool available, no resource gating.
    """
    llm = LLMClient()
    messages: list[dict] = [{"role": "user", "content": user_command}]
    steps: list[dict] = []

    allowed_providers: set[Provider] | None = None
    if team_id is not None:
        allowed_providers = {connection.provider for _, connection, _ in list_channel_connections(session, team_id)}
        if not allowed_providers:
            reply = "This channel doesn't have any Connections assigned yet - ask a Channel Admin to add one before asking Sentinel here."
            _maybe_log_channel_history(session, team_id, user_id, user_command, reply)
            yield {"type": "result", "status": "done", "reply": reply, "steps": steps}
            return

    yield {"type": "status", "message": "Analyzing your request…"}

    for step_num in range(MAX_STEPS):
        if step_num > 0:
            yield {"type": "status", "message": "Thinking…"}
        try:
            message = llm.complete_with_tools(system=_system_prompt(), messages=messages, tools=_tool_schemas(allowed_providers))
        except LLMOverloadedError as exc:
            yield {"type": "result", "status": "error", "reply": str(exc)}
            return
        except LLMError:
            yield {"type": "result", "status": "error", "reply": "Couldn't reach the language model just now - please try again."}
            return

        if not message.tool_calls:
            # A model can stop calling tools yet still produce blank content
            # (confirmed real: gpt-oss-120b's hidden "harmony" reasoning
            # tokens occasionally consumed the whole completion budget
            # before reaching the visible answer, on a real multi-search
            # request) - never ship an empty reply to the user regardless
            # of why it happened.
            reply = (message.content or "").strip() or (
                "I wasn't able to put together a clear answer for that - try rephrasing or narrowing the request."
            )
            _maybe_log_channel_history(session, team_id, user_id, user_command, reply)
            yield {"type": "result", "status": "done", "reply": reply, "steps": steps}
            return

        messages.append(
            {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in message.tool_calls
                ],
            }
        )

        for call in message.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name in WRITE_TOOLS:
                yield {
                    "type": "result",
                    "status": "confirmation_required",
                    "plan": _describe_plan(name, args),
                    "pending_action": {"name": name, "arguments": args},
                    "steps": steps,
                }
                return

            yield {"type": "status", "message": STATUS_MESSAGES.get(name, f"Running {name}…")}
            result = _execute_read_tool(session, workspace_id, name, args, team_id=team_id)
            steps.append({"tool": name, "arguments": args})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})

    reply = "I wasn't able to finish within the step limit - try a more specific request."
    _maybe_log_channel_history(session, team_id, user_id, user_command, reply)
    yield {
        "type": "result",
        "status": "done",
        "reply": reply,
        "steps": steps,
    }


def _maybe_log_channel_history(session: Session, team_id: uuid.UUID | None, user_id: uuid.UUID | None, command: str, reply: str) -> None:
    """Phase 2m's per-Channel AI history - a no-op for the plain,
    non-Channel-scoped AI Command (team_id/user_id both None there)."""
    if team_id is None or user_id is None:
        return
    session.add(ChannelAIHistoryEntry(team_id=team_id, user_id=user_id, command=command, reply=reply))
    session.commit()


def execute_planned_action(session: Session, workspace_id: uuid.UUID, name: str, arguments: dict) -> dict:
    """Only reachable from a route that fires on an explicit user confirm
    click - see api/routes/connections_ai.py. Re-derives the connection from
    workspace_id (never trusts a client-supplied connection/token), so a
    tampered request still can't act outside the caller's own workspace.
    """
    if name != "create_calendar_event":
        raise ValueError(f"Unknown or non-executable action: {name}")

    connection = ConnectionRepository(session, workspace_id).get_by_provider(Provider.GOOGLE_CALENDAR)
    if connection is None:
        raise ValueError("Google Calendar is not connected")

    access_token = get_valid_access_token(session, connection)
    with GoogleCalendarClient(access_token) as client:
        result = client.create_event(
            title=arguments["title"],
            start=datetime.fromisoformat(arguments["start"]),
            end=datetime.fromisoformat(arguments["end"]),
            attendee_emails=arguments.get("attendee_emails") or [],
            create_meet_link=bool(arguments.get("create_meet_link")),
        )

    # Without this, the new event wouldn't show up in Month/Week/Day/Agenda
    # until the next scheduled poll (default every 6h) - same real gap as
    # the manual create endpoint, fixed the same way.
    ingest_connection(session, connection)

    logger.info("orchestrator_action_executed", action=name, workspace_id=str(workspace_id))
    return result


def _get_connection(session: Session, workspace_id: uuid.UUID, team_id: uuid.UUID | None, provider: Provider) -> Connection | None:
    """`team_id=None` (the plain, workspace-wide AI Command) behaves exactly
    as before Phase 2m - just the Workspace's Connection for this provider.
    A Channel-scoped request additionally requires that exact Connection to
    actually be assigned to this Channel (models/channel_connection.py) -
    the tool schema filtering in _tool_schemas already stops the model from
    calling an unavailable tool in the first place, this is the second,
    real enforcement layer in case that ever gets bypassed.
    """
    connection = ConnectionRepository(session, workspace_id).get_by_provider(provider)
    if connection is None:
        return None
    if team_id is not None:
        assigned = session.execute(
            select(ChannelConnection).where(ChannelConnection.team_id == team_id, ChannelConnection.connection_id == connection.id)
        ).scalar_one_or_none()
        if assigned is None:
            return None
    return connection


def _execute_read_tool(session: Session, workspace_id: uuid.UUID, name: str, args: dict, *, team_id: uuid.UUID | None = None) -> dict | list:
    if name == "search_emails":
        connection = _get_connection(session, workspace_id, team_id, Provider.GMAIL)
        if connection is None:
            return {"error": "gmail not connected or not available in this channel"}
        query = build_gmail_query(
            keywords=args.get("keywords"),
            sender=args.get("sender"),
            label_filter=args.get("label_filter"),
            since=args.get("since"),
            until=args.get("until"),
        )
        access_token = get_valid_access_token(session, connection)
        with GmailClient(access_token) as client:
            results = client.search(query, max_results=min(args.get("limit", 10), 30))
        return [
            {
                "id": m["external_id"],
                "subject": m["payload"]["subject"],
                "from": m["payload"]["from"],
                "occurred_at": m["occurred_at"].isoformat(),
                "labels": m["payload"]["label_ids"],
                "url": f"https://mail.google.com/mail/u/0/#all/{m['external_id']}",
            }
            for m in results
        ]

    if name == "read_email_body":
        message_id = args.get("message_id")
        if not message_id:
            return {"error": "missing message_id"}
        connection = _get_connection(session, workspace_id, team_id, Provider.GMAIL)
        if connection is None:
            return {"error": "gmail not connected or not available in this channel"}
        access_token = get_valid_access_token(session, connection)
        with GmailClient(access_token) as client:
            body = client.fetch_message_body(message_id)
        return {"body": (body or "")[:4000]}

    if name == "list_calendar_events":
        if args.get("since") or args.get("until"):
            try:
                since = datetime.fromisoformat(args["since"]) if args.get("since") else datetime.min.replace(tzinfo=timezone.utc)
                until = datetime.fromisoformat(args["until"]) if args.get("until") else datetime.max.replace(tzinfo=timezone.utc)
            except ValueError:
                return {"error": "invalid since/until - use ISO datetimes"}
            events = list_calendar_range(session, workspace_id, since=since, until=until, limit=50)
        else:
            events = list_calendar(session, workspace_id, calendar_range=args.get("range", "upcoming"), limit=20)
        return [
            {
                "id": str(e.id),
                "title": e.payload.get("title"),
                "start": e.payload.get("start"),
                "end": e.payload.get("end"),
                "attendee_count": e.payload.get("attendee_count"),
                "url": e.payload.get("url"),
            }
            for e in events
        ]

    if name == "search_drive":
        connection = _get_connection(session, workspace_id, team_id, Provider.GOOGLE_DRIVE)
        if connection is None:
            return {"error": "google drive not connected or not available in this channel"}
        query = build_drive_query(
            keywords=args.get("keywords"),
            mime_type=args.get("mime_type"),
            modified_after=args.get("modified_after"),
            shared_with_me=args.get("shared_with_me"),
        )
        access_token = get_valid_access_token(session, connection)
        with GoogleDriveClient(access_token) as client:
            files = client.search(query, max_results=min(args.get("limit", 10), 30))
        return files

    if name == "read_drive_file":
        file_id = args.get("file_id")
        if not file_id:
            return {"error": "missing file_id"}
        connection = _get_connection(session, workspace_id, team_id, Provider.GOOGLE_DRIVE)
        if connection is None:
            return {"error": "google drive not connected or not available in this channel"}
        if team_id is not None and not is_resource_allowed(session, team_id, connection.id, file_id):
            # The one place Phase 2m enforces resource-level permission, not
            # just connection-level - a Drive file has a natural discrete
            # resource_key (its own id) to allow-list against, unlike a
            # calendar event or email (see TOOL_PROVIDERS' docstring note).
            return {"error": "This file isn't authorized for this channel - ask a Channel Admin to allow-list it first."}
        access_token = get_valid_access_token(session, connection)
        with GoogleDriveClient(access_token) as client:
            content, mime_or_reason = client.fetch_file_content(file_id)
        if content is None:
            return {"error": mime_or_reason}
        return {"content": content, "mime_type": mime_or_reason}

    if name == "list_meeting_history":
        meeting_range = args.get("range", "upcoming")
        try:
            signals = list_meetings(session, workspace_id, meeting_range=meeting_range, search=args.get("search"), limit=30)
        except ValueError as exc:
            return {"error": str(exc)}
        return [
            {
                "title": s.payload.get("title"),
                "start": s.payload.get("start"),
                "attendee_count": s.payload.get("attendee_count", 0),
                "status": meeting_status(s),
                "calendar_url": s.payload.get("url"),
                "meet_url": s.payload.get("meet_url"),
            }
            for s in signals
        ]

    if name == "find_free_slot":
        date_str = args.get("date")
        if not date_str:
            return {"error": "missing date"}
        gaps = find_free_slots(
            session, workspace_id,
            date=date_str,
            start_hour=int(args.get("start_hour", 9)),
            end_hour=int(args.get("end_hour", 18)),
            duration_minutes=int(args.get("duration_minutes", 30)),
        )
        return {"free_slots": gaps} if gaps else {"free_slots": [], "note": "no gap of the requested length found in that window"}

    if name == "get_holidays":
        since_str, until_str = args.get("since"), args.get("until")
        if not since_str or not until_str:
            return {"error": "missing since/until"}
        try:
            since = datetime.fromisoformat(since_str)
            until = datetime.fromisoformat(until_str)
        except ValueError:
            return {"error": "invalid since/until - use ISO dates"}
        holidays = list_indian_holidays(session, workspace_id, since=since, until=until, state=args.get("state"))
        return {"holidays": holidays} if holidays else {"holidays": [], "note": "no holidays found in that range"}

    return {"error": f"unknown tool {name}"}


def _describe_plan(name: str, args: dict) -> dict:
    if name == "create_calendar_event":
        return {
            "action": "Create Calendar Event",
            "title": args.get("title"),
            "start": args.get("start"),
            "end": args.get("end"),
            "attendees": args.get("attendee_emails") or [],
            "create_meet_link": bool(args.get("create_meet_link")),
        }
    return {"action": name, **args}
