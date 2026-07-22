"""Single choke point for all LLM calls.

Kept as one small file (per ARCHITECTURE.md §2) so swapping Groq for another
provider later is a one-file change, not a refactor of every agent.
"""

import json
import re

import structlog
from groq import APIStatusError, BadRequestError, Groq

from app.core.config import get_settings

logger = structlog.get_logger("sentinel.llm")


class LLMError(Exception):
    pass


class LLMOverloadedError(LLMError):
    """Request exceeded the model's tokens-per-minute ceiling. Not transient -
    retrying sends the same size again - so the orchestrator should surface
    this message directly rather than the generic "try again" fallback.
    """


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = Groq(api_key=settings.groq_api_key)
        self._model = settings.groq_model

    def complete_json(self, *, system: str, user: str, max_retries: int = 2) -> dict:
        """Call the LLM expecting a JSON object back.

        Callers always send pre-computed metrics summaries as `user`, never
        raw signal dumps (ARCHITECTURE.md §4) - this keeps prompts small and
        keeps the model's job to narrative + confidence scoring, not stats.
        """
        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
            except APIStatusError as exc:
                # Every caller of complete_json has a deterministic fallback
                # for exactly this - a channel briefing, an investigation and
                # a proactive situation all degrade to their retrieved
                # evidence without prose. But those fallbacks catch LLMError,
                # and a raw Groq exception sailed straight past them, so a
                # spent quota crashed the request instead of degrading it.
                #
                # Found for real: the free tier's 200k tokens/day ran out
                # mid-session and 32 tests failed with no code change.
                # complete_with_tools had handled this since Phase 2; this
                # path simply never did.
                if exc.status_code in (413, 429):
                    logger.warning("llm_unavailable", attempt=attempt, status=exc.status_code, error=str(exc))
                    raise LLMOverloadedError(
                        "The AI service has hit its usage limit for now - please try again in a little while."
                    ) from exc
                last_err = exc
                logger.warning("llm_request_failed", attempt=attempt, error=str(exc))
                continue

            content = response.choices[0].message.content or ""
            try:
                return json.loads(content)
            except json.JSONDecodeError as exc:
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(0))
                    except json.JSONDecodeError:
                        pass
                last_err = exc
                logger.warning("llm_json_parse_failed", attempt=attempt, error=str(exc))

        raise LLMError(f"LLM did not return valid JSON after {max_retries + 1} attempts") from last_err

    def complete_text(self, *, system: str, messages: list[dict[str, str]], temperature: float = 0.3) -> str:
        """Free-form conversational completion - used by the AI Assistant
        (Phase 1.5), not the agents. Agents always use complete_json, because
        their output is machine-parsed; the assistant's output is read
        directly by a human, so forcing JSON mode here would be wrong.
        """
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system}, *messages],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    def complete_with_tools(self, *, system: str, messages: list[dict], tools: list[dict], max_retries: int = 2):
        """Tool-calling completion - used only by services/orchestrator.py's
        AI Command loop, the one place in the codebase where the model
        decides what to do next rather than narrating something already
        computed. Returns the raw message object (.content / .tool_calls)
        rather than parsed text or JSON, since the caller needs to inspect
        tool_calls itself to drive the next loop iteration.
        """
        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "system", "content": system}, *messages],
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.2,
                    # Confirmed real cause of the 413s: Groq's TPM accounting
                    # reserves room for the model's default max completion
                    # length when max_tokens is left unset, and that
                    # reservation alone was eating most of the 8000 TPM
                    # ceiling - even a first-turn call with almost no
                    # conversation content got rejected. 3000 leaves headroom
                    # under the 8000 TPM ceiling even with a multi-step
                    # conversation, while still covering this model's hidden
                    # "harmony"-format reasoning tokens - at 1024 a
                    # multi-candidate search reliably burned the whole
                    # budget on internal reasoning and returned truncated,
                    # empty final content (confirmed via a real cross-document
                    # search request that got 3 search results but no answer).
                    max_tokens=3000,
                )
                return response.choices[0].message
            except BadRequestError as exc:
                # Confirmed real, reproducible quirk of this model's "harmony"
                # output format: internal channel/commentary tokens
                # occasionally leak into the tool call name (e.g.
                # "search_drive<|channel|>commentary"), which the API then
                # rejects as an unknown tool. A retry (temperature isn't 0)
                # reliably gets a clean call instead of failing the whole
                # AI Command request over a formatting glitch.
                last_err = exc
                logger.warning("llm_tool_call_malformed", attempt=attempt, error=str(exc))
            except APIStatusError as exc:
                if exc.status_code == 413:
                    # Confirmed real: a composite workflow that reads several
                    # Drive files in one loop (cross-document search, doc
                    # comparison, meeting prep) can still push the running
                    # conversation over Groq's 8000 TPM ceiling for this
                    # model/tier even after capping per-file content -
                    # retrying sends the identical size again, so surface a
                    # clear message instead of burning retries or crashing.
                    logger.warning("llm_request_too_large", attempt=attempt, error=str(exc))
                    raise LLMOverloadedError(
                        "That request needs more information than the AI service can handle in one go - "
                        "try narrowing it (e.g. fewer documents, or one file at a time)."
                    ) from exc
                if exc.status_code == 429:
                    # Confirmed real: heavy same-day testing exhausted this
                    # Groq account's on-demand tier daily quota (200k
                    # tokens/day) - retrying immediately can't help (the
                    # error itself reports a real wait time), so fail fast
                    # with an honest message instead of burning 3 identical
                    # retries against a quota that won't refill mid-loop.
                    logger.warning("llm_rate_limited", attempt=attempt, error=str(exc))
                    raise LLMOverloadedError(
                        "The AI service has hit its usage limit for now - please try again in a little while."
                    ) from exc
                last_err = exc
                logger.warning("llm_request_failed", attempt=attempt, error=str(exc))

        raise LLMError(f"LLM tool call failed after {max_retries + 1} attempts") from last_err
