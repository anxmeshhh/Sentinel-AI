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
from datetime import datetime

import structlog
from sqlalchemy.orm import Session

from app.agents.llm import LLMClient, LLMError
from app.integrations.gmail_client import GmailClient
from app.integrations.google_auth import get_valid_access_token
from app.integrations.google_calendar_client import GoogleCalendarClient
from app.models.connection import Provider
from app.models.signal import Signal, SignalType
from app.repositories.connections import ConnectionRepository
from app.services.calendar_query import list_calendar
from app.services.mail_query import list_mail

logger = structlog.get_logger("sentinel.orchestrator")

MAX_STEPS = 5
WRITE_TOOLS = {"create_calendar_event"}

SYSTEM_PROMPT = """You are Sentinel's AI Command interface for a user's connected Google \
services (Gmail, Calendar). You have tools to search email metadata, read one specific email's \
full content, list calendar events, and create a new calendar event (optionally with a Google \
Meet link). Use tools to gather whatever real information you actually need before answering - \
never invent an email, event, person, or detail that a tool didn't return. If the request \
requires creating or changing something (like scheduling a meeting), call create_calendar_event \
as soon as you have enough information - it will not actually run until the user confirms it \
themselves, so you don't need to ask permission first, just propose the concrete action. Keep \
your final answer concise and grounded only in what the tools returned.

Formatting: you're writing for a narrow chat panel, not a document. Never use markdown tables \
(pipe characters) - they don't fit and render unreadably. For a list of emails or events, use a \
short numbered or bulleted list instead, one item per line, with just the essentials (sender or \
title, and the one detail that matters most) - not a dump of every field a tool returned."""


@dataclass
class OrchestrationResult:
    status: str  # "done" | "confirmation_required" | "error"
    reply: str | None = None
    plan: dict | None = None
    pending_action: dict | None = None
    steps: list[dict] = field(default_factory=list)


def _tool_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_emails",
                "description": "Search recent email metadata - subject, sender, date, labels. Never message bodies.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filter": {
                            "type": "string",
                            "enum": ["recent", "starred", "important", "unread", "spam", "top"],
                        },
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["filter"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_email_body",
                "description": "Fetch one specific email's full content by its id (from search_emails results). Live fetch, never stored.",
                "parameters": {
                    "type": "object",
                    "properties": {"signal_id": {"type": "string"}},
                    "required": ["signal_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_calendar_events",
                "description": "List the user's calendar events.",
                "parameters": {
                    "type": "object",
                    "properties": {"range": {"type": "string", "enum": ["upcoming", "past"]}},
                    "required": ["range"],
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


def run_command(session: Session, workspace_id: uuid.UUID, user_command: str) -> OrchestrationResult:
    llm = LLMClient()
    messages: list[dict] = [{"role": "user", "content": user_command}]
    steps: list[dict] = []

    for _ in range(MAX_STEPS):
        try:
            message = llm.complete_with_tools(system=SYSTEM_PROMPT, messages=messages, tools=_tool_schemas())
        except LLMError:
            return OrchestrationResult(status="error", reply="Couldn't reach the language model just now - please try again.")

        if not message.tool_calls:
            return OrchestrationResult(status="done", reply=message.content or "", steps=steps)

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
                return OrchestrationResult(
                    status="confirmation_required",
                    plan=_describe_plan(name, args),
                    pending_action={"name": name, "arguments": args},
                    steps=steps,
                )

            result = _execute_read_tool(session, workspace_id, name, args)
            steps.append({"tool": name, "arguments": args})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})

    return OrchestrationResult(
        status="done",
        reply="I wasn't able to finish within the step limit - try a more specific request.",
        steps=steps,
    )


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
    logger.info("orchestrator_action_executed", action=name, workspace_id=str(workspace_id))
    return result


def _execute_read_tool(session: Session, workspace_id: uuid.UUID, name: str, args: dict) -> dict | list:
    if name == "search_emails":
        items = list_mail(session, workspace_id, mail_filter=args.get("filter", "recent"), limit=min(args.get("limit", 10), 30))
        return [
            {
                "id": str(i.id),
                "subject": i.payload.get("subject"),
                "from": i.payload.get("from"),
                "occurred_at": i.occurred_at.isoformat(),
                "labels": i.payload.get("label_ids", []),
            }
            for i in items
        ]

    if name == "read_email_body":
        try:
            signal_id = uuid.UUID(args["signal_id"])
        except (KeyError, ValueError):
            return {"error": "invalid signal_id"}
        signal = session.get(Signal, signal_id)
        if signal is None or signal.workspace_id != workspace_id or signal.type != SignalType.EMAIL:
            return {"error": "email not found"}
        connection = ConnectionRepository(session, workspace_id).get_by_provider(Provider.GMAIL)
        if connection is None:
            return {"error": "gmail not connected"}
        access_token = get_valid_access_token(session, connection)
        with GmailClient(access_token) as client:
            body = client.fetch_message_body(signal.external_id)
        return {"subject": signal.payload.get("subject"), "from": signal.payload.get("from"), "body": (body or "")[:4000]}

    if name == "list_calendar_events":
        events = list_calendar(session, workspace_id, calendar_range=args.get("range", "upcoming"), limit=20)
        return [
            {
                "id": str(e.id),
                "title": e.payload.get("title"),
                "start": e.payload.get("start"),
                "end": e.payload.get("end"),
                "attendee_count": e.payload.get("attendee_count"),
            }
            for e in events
        ]

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
