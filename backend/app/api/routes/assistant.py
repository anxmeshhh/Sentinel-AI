"""AI Assistant - the one place a chat UI is primary (IA.md §2.2), scoped to
whichever workspace is active. Deliberately still secondary to the pushed
brief everywhere else in the product (PRD principle #1) - this exists so a
user can ask a follow-up question about their own data, not as the main
way Sentinel communicates.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents.llm import LLMClient, LLMError
from app.api.deps import get_current_user, get_db, get_workspace_id
from app.domain.finding import FindingStatus
from app.integrations.gmail_client import GmailClient
from app.integrations.google_auth import get_valid_access_token
from app.models.connection import Provider
from app.models.user import User
from app.repositories.connections import ConnectionRepository
from app.schemas.assistant import ChatRequest, ChatResponse
from app.services.calendar_query import calendar_summary_for_assistant
from app.services.decision_engine import list_decisions
from app.services.findings import list_findings
from app.services.investigation import personal_scope
from app.services.mail_query import find_best_matching_email, mail_summary_for_assistant
from app.services.memory_engine import list_memories
from app.services.situation_engine import list_situations

router = APIRouter(prefix="/assistant", tags=["assistant"])

MAX_HISTORY_MESSAGES = 12

# A body fetch only fires when the question both matches a specific email
# AND looks like it's actually asking about content, not just "is there an
# email from X" (which the structured summary already answers).
CONTENT_INTENT_WORDS = {"say", "said", "about", "content", "read", "summarize", "summarise", "mean", "means"}

SYSTEM_PROMPT = """You are Sentinel's personal AI assistant. You answer questions about the \
user's own workspace using ONLY the context below (what the Intelligence Core has already \
concluded - open findings, correlated situations, learned memory and proposed decisions - plus \
structured summaries of their recent/starred email and upcoming calendar, and, when relevant, the \
live-fetched content of one specific email) plus the ongoing conversation. Everything in the \
context was computed deterministically before you were called: report it, never recompute, \
re-rank or second-guess it. If the answer isn't in the context, say plainly that you don't have \
that information yet rather than guessing - never invent a finding, a number, an email, or a root \
cause that isn't in the context. Be concise and direct."""

# Context caps. The Core can hold hundreds of rows; a chat answer never needs
# more than the top of each list, and every token past that is spend for no
# added accuracy. Kept small deliberately - see _build_context.
MAX_FINDINGS = 8
MAX_SITUATIONS = 5
MAX_MEMORIES = 5
MAX_DECISIONS = 3


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    context = _build_context(session, workspace_id, user.id, payload.message)

    history = [{"role": m.role, "content": m.content} for m in payload.history[-MAX_HISTORY_MESSAGES:]]
    messages = [
        {"role": "user", "content": f"Context about my workspace:\n{context}"},
        {"role": "assistant", "content": "Understood - I'll answer based on that context."},
        *history,
        {"role": "user", "content": payload.message},
    ]

    llm = LLMClient()
    try:
        reply = llm.complete_text(system=SYSTEM_PROMPT, messages=messages)
    except LLMError:
        reply = "I couldn't reach the language model just now - please try again in a moment."

    return ChatResponse(reply=reply)


def _build_context(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID, question: str) -> str:
    """Assemble what the Core already knows. Purely deterministic - every
    line below is a read of an already-computed row, so building the context
    for a chat answer costs zero LLM calls and the reply itself is the only
    one the request makes.

    This used to read the legacy agent Brief and its AgentFindings, which
    meant the Assistant could only discuss whatever the LangGraph pipeline
    last narrated - a narrower and staler view than the Core the rest of the
    product reads. It now reads the same canonical findings, correlated
    situations, memory and decisions the Attention, Situations and Memory
    pages display, so the Assistant and the UI can no longer disagree.
    """
    scope = personal_scope(session, workspace_id, user_id)
    sections = [_core_section(session, workspace_id, scope)]

    mail_summary = mail_summary_for_assistant(session, workspace_id)
    if mail_summary:
        sections.append(mail_summary)

    # Scoped to the caller's own connections, like every other read here: an
    # assistant answering for one person must not be handed another member's
    # meetings as background context.
    calendar_summary = calendar_summary_for_assistant(
        session, workspace_id, connection_ids=scope.connection_ids
    )
    if calendar_summary:
        sections.append(calendar_summary)

    body_section = _maybe_live_email_body(session, workspace_id, user_id, question)
    if body_section:
        sections.append(body_section)

    return "\n\n".join(sections)


def _core_section(session: Session, workspace_id: uuid.UUID, scope) -> str:
    """The Intelligence Core's own output, rendered as compact facts.

    Deliberately terse: the model's job here is to answer a question *about*
    these conclusions, not to re-derive them, so each row contributes one
    short line rather than a paragraph. Truncation is by the Core's own
    ordering (findings are already critical-first, decisions already sorted
    by priority score), never by a judgement made here.
    """
    lines: list[str] = []

    findings = [f for f in list_findings(session, scope) if f.status is FindingStatus.OPEN]
    if findings:
        lines.append(f"Open findings ({len(findings)} total, {MAX_FINDINGS} shown at most, most severe first):")
        for f in findings[:MAX_FINDINGS]:
            provider = f" · {f.provider}" if f.provider else ""
            lines.append(f"- [{f.tier.value}] {f.title}{provider}")
            if f.narrative:
                lines.append(f"  why: {f.narrative}")
    else:
        lines.append("Open findings: none.")

    situations = list_situations(session, workspace_id, scope.key)
    if situations:
        lines.append("")
        lines.append(f"Correlated situations ({len(situations)} open, most severe first):")
        for s in situations[:MAX_SITUATIONS]:
            spread = " · spans multiple services" if s.cross_provider else ""
            lines.append(f"- [{s.severity}] {s.title} ({s.member_count} related findings){spread}")

    memories = list_memories(session, scope)
    if memories:
        lines.append("")
        lines.append("What Sentinel has learned (patterns seen more than once):")
        for m in memories[:MAX_MEMORIES]:
            lines.append(f"- {m.summary}")

    decisions = list_decisions(session, scope)
    if decisions:
        lines.append("")
        lines.append("Proposed next actions (awaiting the user's confirmation - never already done):")
        for d in decisions[:MAX_DECISIONS]:
            lines.append(f"- {d.action} — {d.rationale}")

    return "\n".join(lines)


def _maybe_live_email_body(
    session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID, question: str
) -> str | None:
    """Only fetches a body when the question is confidently about one
    specific email's content - see gmail_client.py's module docstring for
    why this fetch is live and never persisted.

    `user_id` is a parameter because the connection lookup is per-user: this
    function referenced a `user` that was never passed in, so every question
    that reached the fetch raised NameError instead of returning the body.
    """
    q_words = {w.strip(".,?!\"'").lower() for w in question.split()}
    if not (q_words & CONTENT_INTENT_WORDS):
        return None

    signal = find_best_matching_email(session, workspace_id, question)
    if signal is None:
        return None

    connection = ConnectionRepository(session, workspace_id).get_for_user(user_id, Provider.GMAIL)
    if connection is None:
        return None

    try:
        access_token = get_valid_access_token(session, connection)
        with GmailClient(access_token) as client:
            body = client.fetch_message_body(signal.external_id)
    except Exception:
        return None

    if not body:
        return None
    subject = signal.payload.get("subject", "(no subject)")
    sender = signal.payload.get("from", "unknown")
    return f'Live-fetched content of the email "{subject}" from {sender} (this is the one instance where full content, not just metadata, is shown - fetched fresh for this question, not stored):\n{body[:4000]}'
