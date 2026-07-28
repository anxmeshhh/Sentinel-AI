"""Slack OAuth v2 + identity, driven explicitly.

Slack's OAuth v2 differs from the OAuth authlib assumes: bot scopes are
comma-separated in the authorize URL, and the token response is non-standard -
the bot token arrives at `access_token` alongside `team` and `authed_user`
rather than a plain bearer envelope. Doing the exchange by hand here is more
predictable than configuring authlib around those quirks, and it keeps the
whole Slack auth surface in one readable place.

Phase 0 needs exactly three things: the URL to send the user to, the code->bot
token exchange, and an identity check (`auth.test`) that both verifies the
token and returns the workspace it belongs to.
"""

from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
TOKEN_URL = "https://slack.com/api/oauth.v2.access"
AUTH_TEST_URL = "https://slack.com/api/auth.test"

# v1 scopes: read-only, public channels only (see the design review). The bot
# only ever sees channels it is invited to, which is the access boundary.
BOT_SCOPES = ["channels:read", "channels:history", "users:read", "reactions:read"]


class SlackAuthError(Exception):
    """Slack answered but refused - a bad/expired code, a scope problem, or a
    revoked token. Carries Slack's own error string, which is specific."""


def authorize_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    """Where to send the user to grant the bot. Scopes are comma-separated -
    the one thing Slack v2 wants that generic OAuth helpers get wrong."""
    return f"{AUTHORIZE_URL}?" + urlencode({
        "client_id": client_id,
        "scope": ",".join(BOT_SCOPES),
        "redirect_uri": redirect_uri,
        "state": state,
    })


def exchange_code(*, client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    """Trade the OAuth code for a bot token. Returns Slack's full response
    (access_token = the xoxb bot token, plus team/authed_user); raises
    SlackAuthError with Slack's own error if `ok` is false."""
    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        raise SlackAuthError(data.get("error", "oauth_exchange_failed"))
    return data


def auth_test(bot_token: str) -> dict:
    """Verify a bot token and learn whose workspace it is. Returns team/team_id/
    user_id/url; raises SlackAuthError if the token is not (or no longer) good -
    the same call that later detects revocation."""
    resp = httpx.post(AUTH_TEST_URL, headers={"Authorization": f"Bearer {bot_token}"}, timeout=15)
    data = resp.json()
    if not data.get("ok"):
        raise SlackAuthError(data.get("error", "auth_test_failed"))
    return data
