"""Executive Agent: synthesizes every specialist agent's findings into the
one thing users actually read - a ranked, narrated daily brief.

Phase 1 only has one specialist agent feeding it (Engineering), but this
takes `list[Finding]` regardless of which agent produced them, so Phase 2's
cross-agent correlation is additive logic here, not a rewrite
(ARCHITECTURE.md §4, §9).
"""

import structlog

from app.agents.llm import LLMClient, LLMError
from app.models.finding import Finding

logger = structlog.get_logger("sentinel.agents.executive")

MAX_FINDINGS_IN_BRIEF = 5

SYSTEM_PROMPT = """You are the Executive Agent inside Sentinel, an operations intelligence \
platform. You are given the top-ranked findings across all of a company's specialist agents for \
one connection. Write a 2-3 sentence narrative for company leadership: name the single most \
important risk, what happens if it's ignored, and point at the top suggested action. Ground \
everything only in the findings given - do not invent details. Respond as JSON: \
{"narrative": str}."""


class ExecutiveAgent:
    name = "executive"

    def __init__(self, llm: LLMClient | None = None):
        self._llm = llm or LLMClient()

    def synthesize(self, findings: list[Finding], connection_label: str) -> tuple[str, list[str]]:
        if not findings:
            return "No findings above the confidence threshold today.", []

        ranked = sorted(findings, key=lambda f: f.severity * f.confidence, reverse=True)
        top = ranked[:MAX_FINDINGS_IN_BRIEF]

        try:
            result = self._llm.complete_json(system=SYSTEM_PROMPT, user=_render_findings(top, connection_label))
            narrative = result.get("narrative") or _fallback_narrative(top, connection_label)
        except LLMError:
            logger.warning("executive_agent_llm_failed", finding_count=len(top))
            narrative = _fallback_narrative(top, connection_label)

        return narrative, [str(f.id) for f in top]


def _render_findings(findings: list[Finding], connection_label: str) -> str:
    lines = [f"Connection: {connection_label}", ""]
    for f in findings:
        lines.append(
            f"- [{f.agent}] {f.summary} (severity={f.severity:.2f}, confidence={f.confidence:.2f})\n"
            f"  root_cause: {f.root_cause}\n"
            f"  suggested_action: {f.suggested_action}"
        )
    return "\n".join(lines)


def _fallback_narrative(findings: list[Finding], connection_label: str) -> str:
    """Used only if the LLM call fails - never silently produce an empty brief."""
    if not findings:
        return f"{connection_label}: no findings above the confidence threshold today."
    top = findings[0]
    return f"{connection_label}: highest-priority risk is '{top.summary}'. Suggested action: {top.suggested_action}"
