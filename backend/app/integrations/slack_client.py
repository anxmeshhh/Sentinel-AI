"""A thin Slack Web API client - read-only, the four scopes and nothing more.

Like github_client.py, this is where the network lives, kept at the edge so the
services and routes that use it can be reasoned about (and tested) without a
Slack in the loop. Phase 1 needs exactly one capability: discover the channels
this workspace has, and whether the bot is a member of each (membership is what
lets it later read history).
"""

import httpx
import structlog

logger = structlog.get_logger("sentinel.slack_client")

API_BASE = "https://slack.com/api"


class SlackClientError(Exception):
    """Slack answered with ok:false - carries Slack's own error string."""


class SlackClient:
    def __init__(self, bot_token: str, timeout: float = 15.0):
        self._client = httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {bot_token}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SlackClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def list_channels(self, limit: int = 1000) -> list[dict]:
        """Every public channel in the workspace, paginated. `is_member` is the
        one that matters operationally: the bot can *list* any public channel
        (channels:read), but can only later read a channel's history if it has
        been invited to it. Public only, non-archived, per the Phase 0 scopes."""
        channels: list[dict] = []
        cursor: str | None = None
        while len(channels) < limit:
            params: dict = {"types": "public_channel", "exclude_archived": "true", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = self._client.get("/conversations.list", params=params)
            data = resp.json()
            if not data.get("ok"):
                raise SlackClientError(data.get("error", "conversations_list_failed"))
            for ch in data.get("channels", []):
                channels.append({
                    "id": ch["id"],
                    "name": ch.get("name") or ch["id"],
                    "is_member": bool(ch.get("is_member")),
                    "num_members": ch.get("num_members"),
                    "topic": (ch.get("topic") or {}).get("value") or "",
                    "purpose": (ch.get("purpose") or {}).get("value") or "",
                })
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                break
        return channels
