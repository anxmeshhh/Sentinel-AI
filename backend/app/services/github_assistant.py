"""Sentinel's GitHub operations advisor.

The same interaction model as the Google assistant - a prompt, a visible trail,
a grounded answer with sources - but built the way Sentinel is built: it reads
the GitHub state Sentinel has *already ingested* (repositories, priority,
health, commit activity, stalled-repo situations), not the live GitHub API.
That is the whole product thesis applied to the assistant - intelligence over
the data Sentinel already analysed, not a second GitHub client.

Deterministic-first, like everything else here: the GitHub state is gathered by
code, and the model's only job is to read that state back operationally. It is
permanently scoped to the caller's own GitHub, so a user never has to say
"GitHub" or name a repository - every question is assumed to be about theirs.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.llm import LLMClient, LLMError
from app.models.signal import Signal, SignalType
from app.models.situation import ProactiveKind
from app.services.connection_state import connection_state
from app.services.github_connections import monitored_repositories
from app.services.investigation import personal_scope
from app.services.proactive import list_situations

logger = structlog.get_logger("sentinel.github_assistant")

_RECENT_WINDOW_DAYS = 7
_ACTIVITY_WINDOW_DAYS = 30


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def github_context(session: Session, workspace_id, user_id) -> dict:
    """Everything the advisor reasons over, gathered deterministically from
    ingested signals - no LLM, no GitHub round trip."""
    now = datetime.now(timezone.utc)
    repos = monitored_repositories(session, workspace_id, user_id)

    repo_rows: list[dict] = []
    recent_commits: list[dict] = []
    for c in repos:
        newest = session.execute(
            select(Signal)
            .where(Signal.connection_id == c.id, Signal.type == SignalType.COMMIT)
            .order_by(Signal.occurred_at.desc())
            .limit(1)
        ).scalars().first()
        commits_7d = session.execute(
            select(func.count(Signal.id)).where(
                Signal.connection_id == c.id,
                Signal.type == SignalType.COMMIT,
                Signal.occurred_at >= now - timedelta(days=_RECENT_WINDOW_DAYS),
            )
        ).scalar() or 0
        commits_30d = session.execute(
            select(func.count(Signal.id)).where(
                Signal.connection_id == c.id,
                Signal.type == SignalType.COMMIT,
                Signal.occurred_at >= now - timedelta(days=_ACTIVITY_WINDOW_DAYS),
            )
        ).scalar() or 0
        last_at = _aware(newest.occurred_at) if newest else None
        repo_rows.append({
            "full_name": c.full_name,
            "priority": c.priority.value,
            "state": connection_state(c).value,
            "last_commit_days": (now - last_at).days if last_at else None,
            "last_commit_actor": (newest.actor if newest else None),
            "commits_7d": int(commits_7d),
            "commits_30d": int(commits_30d),
            "url": f"https://github.com/{c.full_name}",
        })

        # The actual recent changes, so "what changed this week" has substance.
        for sig in session.execute(
            select(Signal)
            .where(
                Signal.connection_id == c.id,
                Signal.type == SignalType.COMMIT,
                Signal.occurred_at >= now - timedelta(days=_RECENT_WINDOW_DAYS),
            )
            .order_by(Signal.occurred_at.desc())
            .limit(15)
        ).scalars():
            message = (sig.payload or {}).get("message") or ""
            recent_commits.append({
                "repo": c.full_name,
                "message": message.splitlines()[0][:140] if message else "(no message)",
                "actor": sig.actor,
                "days_ago": (now - _aware(sig.occurred_at)).days,
            })

    scope = personal_scope(session, workspace_id, user_id)
    risks = [
        s.title for s in list_situations(session, scope) if s.kind == ProactiveKind.RESOURCE_STALLED
    ]

    recent_commits.sort(key=lambda x: x["days_ago"])
    return {"repos": repo_rows, "recent_commits": recent_commits[:25], "risks": risks}


def _render_context(ctx: dict) -> str:
    if not ctx["repos"]:
        return "This user is not monitoring any GitHub repositories yet."

    lines = [f"Repositories monitored: {len(ctx['repos'])}"]
    for r in ctx["repos"]:
        quiet = "no commits yet" if r["last_commit_days"] is None else f"last commit {r['last_commit_days']}d ago"
        lines.append(
            f"- {r['full_name']} — priority {r['priority']}, health {r['state']}, "
            f"{quiet}, {r['commits_7d']} commits in 7d, {r['commits_30d']} in 30d"
        )

    if ctx["risks"]:
        lines.append("")
        lines.append("Active risks Sentinel has already flagged:")
        lines.extend(f"- {t}" for t in ctx["risks"])

    if ctx["recent_commits"]:
        lines.append("")
        lines.append("Recent commits (last 7 days):")
        for c in ctx["recent_commits"]:
            lines.append(f"- {c['repo']}: \"{c['message']}\" by {c['actor']} ({c['days_ago']}d ago)")
    else:
        lines.append("")
        lines.append("No commits landed in the last 7 days across any monitored repository.")

    return "\n".join(lines)


_SYSTEM = """You are Sentinel's GitHub operations advisor. Sentinel has already \
analysed this user's GitHub; the current state is given below. You are \
permanently scoped to THIS user's GitHub, so never ask them to name a \
repository or say "GitHub" - assume every question is about their repositories.

Rules:
- Ground every statement in the state below. Never invent a repository, commit, \
pull request, or issue.
- Sentinel currently tracks commit activity and repository health. It does NOT \
yet track pull requests or issues. If asked about PRs or issues, say plainly \
that Sentinel is not tracking those yet - do not guess or fabricate them.
- Lead with what needs attention. "At risk" means a CRITICAL repository that has \
gone quiet, an unhealthy connection, or an important repository inactive for a \
long time. A quiet NON-critical repository is usually just finished - say so \
rather than raising a false alarm.
- Refer to repositories by name. Be concise and operational - a short paragraph \
or a few bullets, a briefing not an essay. Answer only what was asked."""


def _sources(ctx: dict) -> list[dict]:
    # The repositories the advisor reasoned over become navigable sources, the
    # same way the Google assistant cites the emails and files it used.
    return [
        {
            "kind": "repo",
            "title": r["full_name"],
            "meta": f"{r['priority'].lower()} · {r['state']}",
            "url": r["url"],
        }
        for r in ctx["repos"][:8]
    ]


def answer_github_stream(session: Session, workspace_id, user_id, question: str) -> Iterator[dict]:
    """Yield the same event shape the Google command stream uses: status steps
    as they happen, then one result with the answer and its sources."""
    yield {"type": "status", "message": "Reading your repositories…"}
    ctx = github_context(session, workspace_id, user_id)

    if not ctx["repos"]:
        yield {
            "type": "result",
            "status": "done",
            "reply": "You're not monitoring any GitHub repositories yet. Add one from the GitHub connection page and I can start advising on it.",
            "sources": [],
        }
        return

    yield {"type": "status", "message": "Analysing activity and risks…"}
    prompt = f"{_render_context(ctx)}\n\nQuestion: {question}"
    try:
        reply = LLMClient().complete_text(
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except LLMError as exc:
        logger.warning("github_assistant_llm_failed", error=str(exc)[:200])
        yield {
            "type": "result",
            "status": "error",
            "reply": "Sentinel couldn't complete that just now. Nothing was changed.",
            "sources": [],
        }
        return

    yield {"type": "result", "status": "done", "reply": reply, "sources": _sources(ctx)}
