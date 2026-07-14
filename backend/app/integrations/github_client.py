"""GitHub REST client.

Hard constraint (PRD SS7, ARCHITECTURE SS6): this client fetches PR/commit/issue/
review METADATA ONLY - titles, timestamps, authors, file paths, add/delete
counts, review state. It never requests diff/patch bodies or file contents,
so there is no code path by which source code can reach the LLM layer.

Runs inside Celery workers (separate OS processes), so a blocking/sync
httpx.Client is the right tool here - unlike the FastAPI request layer, there
is no shared event loop to protect from blocking.
"""

import time
from datetime import datetime, timezone

import httpx
import structlog

logger = structlog.get_logger("sentinel.github")

GITHUB_API = "https://api.github.com"
RATE_LIMIT_FLOOR = 50  # stop and sleep before hitting 0, don't wait for a 403
MAX_RETRIES = 3


class GitHubClientError(Exception):
    pass


class GitHubClient:
    def __init__(self, token: str, timeout: float = 20.0):
        self._client = httpx.Client(
            base_url=GITHUB_API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- low-level request with rate-limit + retry handling ----

    def _request(self, method: str, url: str, params: dict | None = None) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self._client.request(method, url, params=params)
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning("github_transport_error", attempt=attempt, url=url, error=str(exc))
                time.sleep(min(2**attempt, 10))
                continue

            remaining = int(resp.headers.get("x-ratelimit-remaining", "1"))
            reset_at = int(resp.headers.get("x-ratelimit-reset", "0"))

            if resp.status_code == 403 and remaining == 0:
                sleep_for = max(reset_at - int(time.time()), 1)
                logger.warning("github_rate_limited", sleep_seconds=sleep_for)
                time.sleep(min(sleep_for, 120))
                continue

            if resp.status_code >= 500:
                logger.warning("github_server_error", status=resp.status_code, attempt=attempt)
                time.sleep(min(2**attempt, 10))
                continue

            if remaining < RATE_LIMIT_FLOOR:
                sleep_for = max(reset_at - int(time.time()), 0)
                if sleep_for > 0:
                    logger.info("github_rate_limit_floor_hit", remaining=remaining, sleep_seconds=sleep_for)
                    time.sleep(min(sleep_for, 120))

            resp.raise_for_status()
            return resp

        raise GitHubClientError(f"GitHub request failed after {MAX_RETRIES} attempts: {url}") from last_exc

    def _paginated(self, url: str, params: dict) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            resp = self._request("GET", url, params={**params, "per_page": 100, "page": page})
            batch = resp.json()
            if not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return items

    # ---- normalized, metadata-only fetchers ----

    def fetch_pull_requests(self, org: str, repo: str, since: datetime) -> list[dict]:
        raw = self._paginated(
            f"/repos/{org}/{repo}/pulls",
            {"state": "all", "sort": "updated", "direction": "desc"},
        )
        results = []
        for pr in raw:
            updated_at = _parse_ts(pr["updated_at"])
            if updated_at < since:
                break  # sorted desc by update time; nothing older matters
            results.append(
                {
                    "external_id": str(pr["number"]),
                    "actor": pr["user"]["login"],
                    "occurred_at": _parse_ts(pr["created_at"]),
                    "payload": {
                        "number": pr["number"],
                        "title": pr["title"],
                        "state": pr["state"],
                        "author": pr["user"]["login"],
                        "created_at": pr["created_at"],
                        "updated_at": pr["updated_at"],
                        "merged_at": pr.get("merged_at"),
                        "closed_at": pr.get("closed_at"),
                        "additions": pr.get("additions"),
                        "deletions": pr.get("deletions"),
                        "changed_files": pr.get("changed_files"),
                        "requested_reviewers": [r["login"] for r in pr.get("requested_reviewers", [])],
                        "url": pr["html_url"],
                        "base_branch": pr["base"]["ref"],
                    },
                }
            )
        return results

    def fetch_pr_changed_dirs(self, org: str, repo: str, pr_number: int) -> list[str]:
        """Top-level directories touched by a PR - used for hotspot detection.

        GitHub's /files endpoint includes a `patch` field (the actual diff
        hunk) by default. We deliberately read only `filename` and discard
        everything else in the response - the diff content never leaves this
        function, let alone reaches storage or the LLM (PRD SS7).
        """
        raw = self._paginated(f"/repos/{org}/{repo}/pulls/{pr_number}/files", {})
        dirs = set()
        for f in raw:
            filename = f["filename"]
            dirs.add(filename.split("/")[0] if "/" in filename else filename)
        return sorted(dirs)

    def fetch_reviews(self, org: str, repo: str, pr_number: int) -> list[dict]:
        raw = self._paginated(f"/repos/{org}/{repo}/pulls/{pr_number}/reviews", {})
        return [
            {
                "external_id": str(r["id"]),
                "actor": (r.get("user") or {}).get("login", "unknown"),
                "occurred_at": _parse_ts(r["submitted_at"]) if r.get("submitted_at") else None,
                "payload": {
                    "pr_number": pr_number,
                    "state": r["state"],
                    "submitted_at": r.get("submitted_at"),
                },
            }
            for r in raw
            if r.get("submitted_at")
        ]

    def fetch_commits(self, org: str, repo: str, since: datetime) -> list[dict]:
        raw = self._paginated(
            f"/repos/{org}/{repo}/commits",
            {"since": since.astimezone(timezone.utc).isoformat()},
        )
        results = []
        for c in raw:
            commit = c["commit"]
            author_login = (c.get("author") or {}).get("login") or commit["author"]["name"]
            results.append(
                {
                    "external_id": c["sha"],
                    "actor": author_login,
                    "occurred_at": _parse_ts(commit["author"]["date"]),
                    "payload": {
                        "sha": c["sha"],
                        "author": author_login,
                        # first line only - a summary, never the full message/diff body
                        "message_summary": commit["message"].splitlines()[0][:200],
                        "url": c["html_url"],
                    },
                }
            )
        return results

    def fetch_issues(self, org: str, repo: str, since: datetime) -> list[dict]:
        raw = self._paginated(
            f"/repos/{org}/{repo}/issues",
            {"state": "all", "since": since.astimezone(timezone.utc).isoformat()},
        )
        results = []
        for issue in raw:
            if "pull_request" in issue:
                continue  # GitHub's /issues endpoint includes PRs; we handle those separately
            results.append(
                {
                    "external_id": str(issue["number"]),
                    "actor": issue["user"]["login"],
                    "occurred_at": _parse_ts(issue["created_at"]),
                    "payload": {
                        "number": issue["number"],
                        "title": issue["title"],
                        "state": issue["state"],
                        "author": issue["user"]["login"],
                        "created_at": issue["created_at"],
                        "closed_at": issue.get("closed_at"),
                        "url": issue["html_url"],
                    },
                }
            )
        return results


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
