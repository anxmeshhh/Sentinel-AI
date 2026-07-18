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
from app.api.deps import get_db, get_workspace_id
from app.integrations.gmail_client import GmailClient
from app.integrations.google_auth import get_valid_access_token
from app.models.connection import Provider
from app.repositories.briefs import BriefRepository
from app.repositories.connections import ConnectionRepository
from app.repositories.findings import FindingRepository
from app.schemas.assistant import ChatRequest, ChatResponse
from app.services.calendar_query import calendar_summary_for_assistant
from app.services.mail_query import find_best_matching_email, mail_summary_for_assistant

router = APIRouter(prefix="/assistant", tags=["assistant"])

MAX_HISTORY_MESSAGES = 12

# A body fetch only fires when the question both matches a specific email
# AND looks like it's actually asking about content, not just "is there an
# email from X" (which the structured summary already answers).
CONTENT_INTENT_WORDS = {"say", "said", "about", "content", "read", "summarize", "summarise", "mean", "means"}

SYSTEM_PROMPT = """You are Sentinel's personal AI assistant. You answer questions about the \
user's own workspace using ONLY the context below (their latest brief and its findings, plus \
structured summaries of their recent/starred email and upcoming calendar - and, when relevant, the \
live-fetched content of one specific email) plus the ongoing conversation. If the answer isn't in \
the context, say plainly that you don't have that information yet rather than guessing - never \
invent a finding, a number, an email, or a root cause that isn't in the context. Be concise and \
direct."""


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> ChatResponse:
    context = _build_context(session, workspace_id, payload.message)

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


def _build_context(session: Session, workspace_id: uuid.UUID, question: str) -> str:
    sections = [_brief_section(session, workspace_id)]

    mail_summary = mail_summary_for_assistant(session, workspace_id)
    if mail_summary:
        sections.append(mail_summary)

    calendar_summary = calendar_summary_for_assistant(session, workspace_id)
    if calendar_summary:
        sections.append(calendar_summary)

    body_section = _maybe_live_email_body(session, workspace_id, question)
    if body_section:
        sections.append(body_section)

    return "\n\n".join(sections)


def _brief_section(session: Session, workspace_id: uuid.UUID) -> str:
    brief = BriefRepository(session, workspace_id).latest()
    if brief is None:
        return "No brief has been generated for this workspace yet - no findings to discuss."

    findings = FindingRepository(session, workspace_id).for_run(brief.run_id)
    lines = [f"Latest brief ({brief.generated_at.isoformat()}): {brief.narrative}", "", "Findings:"]
    for f in findings:
        lines.append(
            f"- [{f.agent}] {f.summary} (severity={f.severity:.2f}, confidence={f.confidence:.2f})\n"
            f"  root_cause: {f.root_cause}\n"
            f"  suggested_action: {f.suggested_action}"
        )
    if not findings:
        lines.append("(none above the confidence threshold)")
    return "\n".join(lines)


def _maybe_live_email_body(session: Session, workspace_id: uuid.UUID, question: str) -> str | None:
    """Only fetches a body when the question is confidently about one
    specific email's content - see gmail_client.py's module docstring for
    why this fetch is live and never persisted.
    """
    q_words = {w.strip(".,?!\"'").lower() for w in question.split()}
    if not (q_words & CONTENT_INTENT_WORDS):
        return None

    signal = find_best_matching_email(session, workspace_id, question)
    if signal is None:
        return None

    connection = ConnectionRepository(session, workspace_id).get_by_provider(Provider.GMAIL)
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
