import uuid
from datetime import datetime, timedelta, timezone

from app.agents.engineering_agent import EngineeringAgent, _percentile
from app.models.signal import Signal, SignalType

NOW = datetime.now(timezone.utc)


def _pr_signal(*, number, occurred_at, merged_at=None, additions=0, deletions=0, base_branch="main", changed_dirs=None):
    return Signal(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        type=SignalType.PR,
        external_id=str(number),
        actor="author",
        occurred_at=occurred_at,
        payload={
            "number": number,
            "title": f"PR {number}",
            "url": f"https://github.com/org/repo/pull/{number}",
            "author": "author",
            "additions": additions,
            "deletions": deletions,
            "base_branch": base_branch,
            "merged_at": merged_at.isoformat() if merged_at else None,
            "changed_dirs": changed_dirs or [],
            "changed_files": 1,
        },
    )


class FakeLLM:
    def __init__(self, response: dict):
        self._response = response

    def complete_json(self, *, system: str, user: str) -> dict:
        return self._response


def test_percentile_basic():
    assert _percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert _percentile([], 0.9) == 0.0


def test_detect_risky_deploys_flags_fast_unreviewed_large_merge():
    pr = _pr_signal(
        number=482,
        occurred_at=NOW - timedelta(minutes=20),
        merged_at=NOW - timedelta(minutes=9),
        additions=900,
        deletions=400,
    )
    agent = EngineeringAgent(llm=FakeLLM({"results": []}))
    candidates = agent._detect_risky_deploys([pr], reviews_by_pr={})
    assert len(candidates) == 1
    assert candidates[0]["type"] == "risky_deploy"
    assert candidates[0]["metrics"]["pr_number"] == 482


def test_detect_risky_deploys_ignores_reviewed_prs():
    pr = _pr_signal(
        number=483,
        occurred_at=NOW - timedelta(minutes=20),
        merged_at=NOW - timedelta(minutes=9),
        additions=900,
        deletions=400,
    )
    reviewed = Signal(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        type=SignalType.REVIEW_SUBMITTED,
        external_id="483:1",
        actor="reviewer",
        occurred_at=NOW - timedelta(minutes=15),
        payload={"pr_number": 483, "state": "APPROVED"},
    )
    agent = EngineeringAgent(llm=FakeLLM({"results": []}))
    candidates = agent._detect_risky_deploys([pr], reviews_by_pr={"483": [reviewed]})
    assert candidates == []


def test_analyze_suppresses_low_confidence_findings():
    pr = _pr_signal(
        number=100,
        occurred_at=NOW - timedelta(minutes=20),
        merged_at=NOW - timedelta(minutes=5),
        additions=900,
        deletions=400,
    )
    # LLM returns a result for the one candidate, but below the default 0.55 threshold
    fake_llm = FakeLLM(
        {"results": [{"index": 0, "severity": 0.9, "confidence": 0.2, "summary": "x", "root_cause": "y", "suggested_action": "z"}]}
    )
    agent = EngineeringAgent(llm=fake_llm)
    findings = agent.analyze([pr])
    assert findings == []


def test_analyze_keeps_high_confidence_findings():
    pr = _pr_signal(
        number=101,
        occurred_at=NOW - timedelta(minutes=20),
        merged_at=NOW - timedelta(minutes=5),
        additions=900,
        deletions=400,
    )
    fake_llm = FakeLLM(
        {
            "results": [
                {
                    "index": 0,
                    "severity": 0.8,
                    "confidence": 0.9,
                    "summary": "Large unreviewed merge to main",
                    "root_cause": "PR #101 merged 15 minutes after opening with no review",
                    "suggested_action": "Require review on main",
                }
            ]
        }
    )
    agent = EngineeringAgent(llm=fake_llm)
    findings = agent.analyze([pr])
    assert len(findings) == 1
    assert findings[0].type == "risky_deploy"
    assert findings[0].confidence == 0.9
    assert findings[0].evidence["pull_requests"][0]["number"] == 101
