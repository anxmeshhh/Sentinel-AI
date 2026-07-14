"""Engineering Agent: GitHub signals -> bottlenecks, hotspots, inactive
contributors, risky deploys.

Design choice: detection is deterministic Python, not the LLM. The agent
computes real candidates with real evidence (PR numbers, URLs, timestamps)
first; the LLM is only asked to narrate + score confidence for candidates
that already exist, matched back by index. This keeps every Finding's
evidence traceable to actual ingested rows (PRD "Explainable" principle)
instead of trusting the model to invent both the finding and its evidence
from a wall of metrics text.
"""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import structlog

from app.agents.base import SpecialistAgent
from app.agents.llm import LLMClient, LLMError
from app.core.config import get_settings
from app.models.finding import Finding
from app.models.signal import Signal, SignalType

logger = structlog.get_logger("sentinel.agents.engineering")

RECENT_WINDOW = timedelta(days=7)
BASELINE_WINDOW = timedelta(days=30)
MIN_SAMPLE_FOR_LATENCY_TREND = 3
DOMINANT_REVIEWER_SHARE = 0.75
RISKY_DEPLOY_MINUTES = 30
RISKY_DEPLOY_MIN_CHANGED_LINES = 300

SYSTEM_PROMPT = """You are the Engineering Agent inside Sentinel, an operations intelligence \
platform for engineering teams. You are given a list of candidate findings, each with real, \
pre-computed metrics (never raw code) about a GitHub repository. For each candidate, write a \
concise summary, a root_cause sentence grounded ONLY in the numbers given, one concrete \
suggested_action, a severity 0..1, and a confidence 0..1. Do not invent numbers or evidence not \
present in the candidate. If a candidate's metrics do not actually seem meaningful or actionable, \
give it a low confidence rather than omitting it. Respond as JSON: {"results": [{"index": int, \
"severity": float, "confidence": float, "summary": str, "root_cause": str, \
"suggested_action": str}, ...]} with exactly one result per candidate index provided."""


class EngineeringAgent(SpecialistAgent):
    name = "engineering"

    def __init__(self, llm: LLMClient | None = None):
        self._llm = llm or LLMClient()

    def analyze(self, signals: list[Signal]) -> list[Finding]:
        prs = [s for s in signals if s.type == SignalType.PR]
        reviews = [s for s in signals if s.type == SignalType.REVIEW_SUBMITTED]
        commits = [s for s in signals if s.type == SignalType.COMMIT]

        reviews_by_pr: dict[str, list[Signal]] = defaultdict(list)
        for r in reviews:
            pr_number = r.payload.get("pr_number")
            if pr_number is not None:
                reviews_by_pr[str(pr_number)].append(r)

        candidates: list[dict] = []
        bottleneck = self._detect_review_bottleneck(prs, reviews_by_pr)
        if bottleneck:
            candidates.append(bottleneck)
        candidates.extend(self._detect_contributor_drops(prs, commits, reviews))
        candidates.extend(self._detect_risky_deploys(prs, reviews_by_pr))

        if not candidates:
            return []

        try:
            narrated = self._llm.complete_json(
                system=SYSTEM_PROMPT,
                user=_render_candidates(candidates),
            )
        except LLMError:
            logger.warning("engineering_agent_llm_failed", candidate_count=len(candidates))
            return []

        settings = get_settings()
        findings: list[Finding] = []
        for result in narrated.get("results", []):
            idx = result.get("index")
            if idx is None or not (0 <= idx < len(candidates)):
                continue
            confidence = float(result.get("confidence", 0))
            if confidence < settings.min_finding_confidence:
                continue  # suppress low-confidence noise - PRD principle #4
            candidate = candidates[idx]
            findings.append(
                Finding(
                    id=uuid.uuid4(),  # set eagerly (not left to the flush-time column default) so the
                    # Executive Agent can reference finding.id in top_finding_ids before any flush.
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

    def _detect_review_bottleneck(self, prs: list[Signal], reviews_by_pr: dict[str, list[Signal]]) -> dict | None:
        now = datetime.now(timezone.utc)
        recent_latencies, baseline_latencies = [], []
        recent_prs_by_dir: dict[str, list[dict]] = defaultdict(list)

        for pr in prs:
            pr_reviews = reviews_by_pr.get(str(pr.payload["number"]))
            if not pr_reviews:
                continue
            first_review_at = min(r.occurred_at for r in pr_reviews)
            created_at = pr.occurred_at
            latency_hours = (first_review_at - created_at).total_seconds() / 3600
            if latency_hours < 0:
                continue

            age = now - created_at
            if age <= RECENT_WINDOW:
                recent_latencies.append(latency_hours)
                for d in pr.payload.get("changed_dirs", []):
                    recent_prs_by_dir[d].append(
                        {
                            "number": pr.payload["number"],
                            "url": pr.payload["url"],
                            "title": pr.payload["title"],
                            "author": pr.payload["author"],
                            "latency_hours": round(latency_hours, 1),
                            "reviewers": sorted({r.actor for r in pr_reviews}),
                        }
                    )
            elif age <= BASELINE_WINDOW:
                baseline_latencies.append(latency_hours)

        if len(recent_latencies) < MIN_SAMPLE_FOR_LATENCY_TREND:
            return None

        recent_p90 = _percentile(recent_latencies, 0.9)
        baseline_p90 = _percentile(baseline_latencies, 0.9) if baseline_latencies else recent_p90

        if recent_p90 <= baseline_p90 * 1.5:
            return None  # no meaningful worsening trend

        # find the worst directory: highest latency, with a single dominant reviewer
        worst_dir, worst_prs = None, []
        for d, d_prs in recent_prs_by_dir.items():
            if len(d_prs) < 2:
                continue
            avg_latency = sum(p["latency_hours"] for p in d_prs) / len(d_prs)
            reviewer_counts: dict[str, int] = defaultdict(int)
            for p in d_prs:
                for reviewer in p["reviewers"]:
                    reviewer_counts[reviewer] += 1
            if not reviewer_counts:
                continue
            top_reviewer, top_count = max(reviewer_counts.items(), key=lambda kv: kv[1])
            share = top_count / len(d_prs)
            if worst_dir is None or avg_latency > worst_dir[1]:
                worst_dir = (d, avg_latency, top_reviewer, share)
                worst_prs = d_prs

        return {
            "type": "review_bottleneck",
            "metrics": {
                "recent_p90_review_latency_hours": round(recent_p90, 1),
                "baseline_p90_review_latency_hours": round(baseline_p90, 1),
                "sample_size": len(recent_latencies),
                "worst_directory": worst_dir[0] if worst_dir else None,
                "worst_directory_avg_latency_hours": round(worst_dir[1], 1) if worst_dir else None,
                "dominant_reviewer": worst_dir[2] if worst_dir else None,
                "dominant_reviewer_share": round(worst_dir[3], 2) if worst_dir else None,
                "affected_prs": worst_prs or [p for prs_ in recent_prs_by_dir.values() for p in prs_][:6],
            },
            "evidence": {"pull_requests": (worst_prs or [])[:10]},
        }

    def _detect_contributor_drops(self, prs: list[Signal], commits: list[Signal], reviews: list[Signal]) -> list[dict]:
        now = datetime.now(timezone.utc)
        all_activity = prs + commits + reviews
        by_actor_recent: dict[str, int] = defaultdict(int)
        by_actor_baseline: dict[str, int] = defaultdict(int)

        for s in all_activity:
            age = now - s.occurred_at
            if age <= RECENT_WINDOW:
                by_actor_recent[s.actor] += 1
            elif age <= BASELINE_WINDOW:
                by_actor_baseline[s.actor] += 1

        candidates = []
        for actor, baseline_count in by_actor_baseline.items():
            baseline_days = (BASELINE_WINDOW - RECENT_WINDOW).days
            baseline_daily_avg = baseline_count / baseline_days
            if baseline_daily_avg < 0.3:
                continue  # wasn't active enough before to call a "drop" meaningful

            recent_count = by_actor_recent.get(actor, 0)
            recent_daily_avg = recent_count / RECENT_WINDOW.days
            if baseline_daily_avg == 0:
                continue
            ratio = recent_daily_avg / baseline_daily_avg
            if ratio > 0.2:
                continue  # not a meaningful drop

            candidates.append(
                {
                    "type": "contributor_activity_drop",
                    "metrics": {
                        "actor": actor,
                        "recent_daily_avg": round(recent_daily_avg, 2),
                        "baseline_daily_avg": round(baseline_daily_avg, 2),
                        "drop_ratio": round(ratio, 2),
                    },
                    "evidence": {"actor": actor, "recent_activity_count": recent_count, "baseline_activity_count": baseline_count},
                }
            )
        return candidates[:3]  # cap noise - only the most dramatic drops matter

    def _detect_risky_deploys(self, prs: list[Signal], reviews_by_pr: dict[str, list[Signal]]) -> list[dict]:
        candidates = []
        for pr in prs:
            payload = pr.payload
            if payload.get("base_branch") not in ("main", "master") or not payload.get("merged_at"):
                continue
            merged_at = _parse_iso(payload["merged_at"])
            minutes_to_merge = (merged_at - pr.occurred_at).total_seconds() / 60
            changed_lines = (payload.get("additions") or 0) + (payload.get("deletions") or 0)
            has_review = bool(reviews_by_pr.get(str(payload["number"])))

            if minutes_to_merge <= RISKY_DEPLOY_MINUTES and changed_lines >= RISKY_DEPLOY_MIN_CHANGED_LINES and not has_review:
                candidates.append(
                    {
                        "type": "risky_deploy",
                        "metrics": {
                            "pr_number": payload["number"],
                            "title": payload["title"],
                            "minutes_to_merge": round(minutes_to_merge, 1),
                            "additions": payload.get("additions"),
                            "deletions": payload.get("deletions"),
                            "changed_files": payload.get("changed_files"),
                            "base_branch": payload["base_branch"],
                            "had_review": has_review,
                        },
                        "evidence": {"pull_requests": [{"number": payload["number"], "url": payload["url"]}]},
                    }
                )
        return candidates[:3]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _render_candidates(candidates: list[dict]) -> str:
    lines = []
    for i, c in enumerate(candidates):
        lines.append(f"Candidate {i} ({c['type']}): {c['metrics']}")
    return "\n".join(lines)
