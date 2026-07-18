"""Email summarization - the one place a full email body gets sent to the
LLM, and only on demand (see api/routes/mail.py's /summary endpoint). Always
cached afterward via EmailSummaryRepository so the same email is never
re-fetched or re-summarized - the token-efficiency requirement this exists
for in the first place.
"""

import structlog

from app.agents.llm import LLMClient, LLMError

logger = structlog.get_logger("sentinel.mail_summarizer")

SYSTEM_PROMPT = """You summarize a single email for someone deciding whether it needs their \
attention. Given the email's subject, sender, and full body, respond as JSON: {"summary": a \
1-2 sentence plain-language summary, "key_points": a short list (3-5 items, empty if trivial) of \
the most important facts, "action_items": a short list of anything the recipient actually needs \
to do, including any deadline mentioned (empty list if none)}. Ground everything only in the \
email's real content - never invent a deadline or action that isn't actually there."""


def summarize_email(subject: str, sender: str, body: str) -> dict:
    llm = LLMClient()
    user = f"Subject: {subject}\nFrom: {sender}\n\n{body[:8000]}"
    try:
        result = llm.complete_json(system=SYSTEM_PROMPT, user=user)
    except LLMError:
        logger.warning("mail_summarize_failed")
        return {"summary": "Couldn't generate a summary right now - try again in a moment.", "key_points": [], "action_items": []}
    return {
        "summary": result.get("summary", ""),
        "key_points": [p for p in (result.get("key_points") or []) if p],
        "action_items": [a for a in (result.get("action_items") or []) if a],
    }
