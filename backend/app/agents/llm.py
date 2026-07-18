"""Single choke point for all LLM calls.

Kept as one small file (per ARCHITECTURE.md §2) so swapping Groq for another
provider later is a one-file change, not a refactor of every agent.
"""

import json
import re

import structlog
from groq import Groq

from app.core.config import get_settings

logger = structlog.get_logger("sentinel.llm")


class LLMError(Exception):
    pass


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
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
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

    def complete_with_tools(self, *, system: str, messages: list[dict], tools: list[dict]):
        """Tool-calling completion - used only by services/orchestrator.py's
        AI Command loop, the one place in the codebase where the model
        decides what to do next rather than narrating something already
        computed. Returns the raw message object (.content / .tool_calls)
        rather than parsed text or JSON, since the caller needs to inspect
        tool_calls itself to drive the next loop iteration.
        """
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system}, *messages],
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
        )
        return response.choices[0].message
