"""Communication Agent: Gmail/Calendar signals -> stale flagged mail, spam
surges, calendar overload.

Same discipline as the Engineering Agent (see its docstring): detection is
deterministic Python over already-ingested metadata (labels, subject lines,
timestamps) - never a live body fetch, and never raw email content. The LLM
only narrates + scores confidence for candidates that already exist with
real evidence. This agent runs against whatever signals its connection has;
on a GitHub connection it simply finds zero EMAIL/CALENDAR_EVENT signals and
returns nothing, same as the Engineering Agent returns nothing on a Gmail
connection.
"""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import structlog

from app.agents.base import SpecialistAgent
from app.agents.llm import LLMClient, LLMError
from app.core.config import get_settings
from app.models.finding import AgentFinding
from app.models.signal import Signal, SignalType
from app.services.mail_signals import noise_reason, sender_counts

logger = structlog.get_logger("sentinel.agents.communication")

RECENT_WINDOW = timedelta(days=7)
BASELINE_WINDOW = timedelta(days=30)
STALE_FLAGGED_HOURS = 24
CALENDAR_OVERLOAD_HOURS_PER_DAY = 5.0
CALENDAR_BACK_TO_BACK_GAP_MINUTES = 10
CALENDAR_BACK_TO_BACK_MIN_COUNT = 4
MIN_SPAM_BASELINE_FOR_SURGE = 3

SYSTEM_PROMPT = """You are the Communication Agent inside Sentinel, an operations intelligence \
platform. You are given a list of candidate findings, each with real, pre-computed metrics about \
a person's email and calendar activity (never message bodies - subject lines, labels, and \
timestamps only). For each candidate, write a concise summary, a root_cause sentence grounded \
ONLY in the numbers given, one concrete suggested_action, a severity 0..1, and a confidence 0..1. \
Do not invent numbers or evidence not present in the candidate. Keep tone practical and \
operational, not alarmist - this is about surfacing things worth a look, not diagnosing anyone. \
If a candidate's metrics do not actually seem meaningful or actionable, give it a low confidence \
rather than omitting it. Respond as JSON: {"results": [{"index": int, "severity": float, \
"confidence": float, "summary": str, "root_cause": str, "suggested_action": str}, ...]} with \
exactly one result per candidate index provided."""


class CommunicationAgent(SpecialistAgent):
    name = "communication"

    def __init__(self, llm: LLMClient | None = None):
        self._llm = llm or LLMClient()

    def analyze(self, signals: list[Signal]) -> list[AgentFinding]:
        emails = [s for s in signals if s.type == SignalType.EMAIL]
        events = [s for s in signals if s.type == SignalType.CALENDAR_EVENT]

        candidates: list[dict] = []
        stale = self._detect_stale_flagged_mail(emails)
        if stale:
            candidates.append(stale)
        surge = self._detect_spam_surge(emails)
        if surge:
            candidates.append(surge)
        candidates.extend(self._detect_calendar_overload(events))

        if not candidates:
            return []

        try:
            narrated = self._llm.complete_json(system=SYSTEM_PROMPT, user=_render_candidates(candidates))
        except LLMError:
            logger.warning("communication_agent_llm_failed", candidate_count=len(candidates))
            return []

        settings = get_settings()
        findings: list[AgentFinding] = []
        for result in narrated.get("results", []):
            idx = result.get("index")
            if idx is None or not (0 <= idx < len(candidates)):
                continue
            confidence = float(result.get("confidence", 0))
            if confidence < settings.min_finding_confidence:
                continue
            candidate = candidates[idx]
            findings.append(
                AgentFinding(
                    id=uuid.uuid4(),
                    agent=self.name,
                    type=candidate["type"],
                    severity=max(0.0, min(1.0, float(result.get("severity", 0.5)))),
                    confidence=max(0.0, min(1.0, confidence)),
                    summary=result.get("summary", ""),
                    root_cause=result.get("root_cause", ""),
                    suggested_action=result.get("suggested_action", ""),
                    evidence=candidate["evidence"],
                )
            )
        return findings

    # ---- deterministic candidate detection ----

    def _detect_stale_flagged_mail(self, emails: list[Signal]) -> dict | None:
        now = datetime.now(timezone.utc)
        # Same noise filter the attention engine uses (Phase 2v). Without
        # it this agent produced findings like "12 important emails need
        # attention" listing Pinterest recommendations and a Welcome
        # email - and because high-severity findings are themselves
        # promoted into the attention feed, that noise re-entered through
        # the back door after being filtered out of the front.
        counts = sender_counts([e.payload for e in emails])
        stale = []
        for e in emails:
            labels = set(e.payload.get("label_ids", []))
            if "UNREAD" not in labels or not ({"IMPORTANT", "STARRED"} & labels):
                continue
            # Starring is an explicit human judgment and always survives;
            # everything else must clear the bulk/automated check.
            if "STARRED" not in labels and noise_reason(e.payload, counts) is not None:
                continue
            age_hours = (now - e.occurred_at).total_seconds() / 3600
            if age_hours >= STALE_FLAGGED_HOURS:
                stale.append(
                    {
                        "subject": e.payload.get("subject", "(no subject)"),
                        "from": e.payload.get("from", "unknown"),
                        "age_hours": round(age_hours, 1),
                        "starred": "STARRED" in labels,
                        "important": "IMPORTANT" in labels,
                    }
                )

        if not stale:
            return None
        stale.sort(key=lambda m: m["age_hours"], reverse=True)

        return {
            "type": "stale_flagged_mail",
            "metrics": {
                "count": len(stale),
                "oldest_age_hours": stale[0]["age_hours"],
                "samples": stale[:5],
            },
            "evidence": {"emails": stale[:5]},
        }

    def _detect_spam_surge(self, emails: list[Signal]) -> dict | None:
        now = datetime.now(timezone.utc)
        recent_count, baseline_count = 0, 0
        for e in emails:
            if "SPAM" not in set(e.payload.get("label_ids", [])):
                continue
            age = now - e.occurred_at
            if age <= RECENT_WINDOW:
                recent_count += 1
            elif age <= BASELINE_WINDOW:
                baseline_count += 1

        baseline_days = (BASELINE_WINDOW - RECENT_WINDOW).days
        baseline_daily_avg = baseline_count / baseline_days
        recent_daily_avg = recent_count / RECENT_WINDOW.days

        if baseline_count < MIN_SPAM_BASELINE_FOR_SURGE or baseline_daily_avg == 0:
            return None
        ratio = recent_daily_avg / baseline_daily_avg
        if ratio < 2.0:  # needs to at least double to count as a real surge
            return None

        return {
            "type": "spam_surge",
            "metrics": {
                "recent_daily_avg": round(recent_daily_avg, 2),
                "baseline_daily_avg": round(baseline_daily_avg, 2),
                "surge_ratio": round(ratio, 2),
                "recent_count": recent_count,
            },
            "evidence": {"recent_spam_count": recent_count, "baseline_spam_count": baseline_count},
        }

    def _detect_calendar_overload(self, events: list[Signal]) -> list[dict]:
        now = datetime.now(timezone.utc)
        by_day: dict[str, list[Signal]] = defaultdict(list)
        for e in events:
            age = now - e.occurred_at
            if timedelta(days=-14) <= age <= RECENT_WINDOW:  # includes a small look-ahead window
                by_day[e.occurred_at.date().isoformat()].append(e)

        candidates = []
        for day, day_events in by_day.items():
            spans = sorted(_event_span(e) for e in day_events if _event_span(e))
            if not spans:
                continue
            total_hours = sum((end - start).total_seconds() / 3600 for start, end in spans)

            back_to_back = 0
            for i in range(1, len(spans)):
                gap_minutes = (spans[i][0] - spans[i - 1][1]).total_seconds() / 60
                if 0 <= gap_minutes <= CALENDAR_BACK_TO_BACK_GAP_MINUTES:
                    back_to_back += 1

            if total_hours >= CALENDAR_OVERLOAD_HOURS_PER_DAY or back_to_back >= CALENDAR_BACK_TO_BACK_MIN_COUNT:
                candidates.append(
                    {
                        "type": "calendar_overload",
                        "metrics": {
                            "day": day,
                            "total_meeting_hours": round(total_hours, 1),
                            "meeting_count": len(spans),
                            "back_to_back_count": back_to_back,
                        },
                        "evidence": {
                            "day": day,
                            "titles": [e.payload.get("title", "(no title)") for e in day_events][:10],
                        },
                    }
                )

        candidates.sort(key=lambda c: c["metrics"]["total_meeting_hours"], reverse=True)
        return candidates[:3]


def _event_span(e: Signal) -> tuple[datetime, datetime] | None:
    start_raw, end_raw = e.payload.get("start"), e.payload.get("end")
    if not start_raw or not end_raw:
        return None
    try:
        start = _parse_ts(start_raw)
        end = _parse_ts(end_raw)
    except ValueError:
        return None
    if end <= start:
        return None
    return start, end


def _parse_ts(value: str) -> datetime:
    if "T" not in value:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _render_candidates(candidates: list[dict]) -> str:
    lines = []
    for i, c in enumerate(candidates):
        lines.append(f"Candidate {i} ({c['type']}): {c['metrics']}")
    return "\n".join(lines)
