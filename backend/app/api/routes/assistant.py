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
from app.repositories.briefs import BriefRepository
from app.repositories.findings import FindingRepository
from app.schemas.assistant import ChatRequest, ChatResponse

router = APIRouter(prefix="/assistant", tags=["assistant"])

MAX_HISTORY_MESSAGES = 12

SYSTEM_PROMPT = """You are Sentinel's personal AI assistant. You answer questions about the \
user's own workspace using ONLY the context below (their latest brief and its findings) plus the \
ongoing conversation. If the answer isn't in the context, say plainly that you don't have that \
information yet rather than guessing - never invent a finding, a number, or a root cause that \
isn't in the context. Be concise and direct."""


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> ChatResponse:
    context = _build_context(session, workspace_id)

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


def _build_context(session: Session, workspace_id: uuid.UUID) -> str:
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
