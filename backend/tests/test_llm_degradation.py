"""A spent LLM quota must degrade every feature, never crash one.

Found the hard way: Groq's free tier allows 200k tokens/day, that budget ran
out mid-session, and 32 tests failed with no code change. The cause was not
the quota - it was that `complete_json` let the provider's own exception
escape. Every caller has a careful `except LLMError` fallback (a briefing
without prose, an investigation that still lists its evidence, a situation
that still shows its signals), and none of them ran, because a raw
`APIStatusError` is not an `LLMError`.

`complete_with_tools` had handled this correctly since Phase 2. This is the
regression test for the path that didn't.
"""

import pytest
from groq import APIStatusError

from app.agents.llm import LLMClient, LLMError, LLMOverloadedError


class _FakeResponse:
    """Minimal stand-in for the httpx response an APIStatusError carries."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        self.headers = {}
        self.request = None


def _status_error(status_code: int) -> APIStatusError:
    return APIStatusError(
        "rate limited", response=_FakeResponse(status_code), body={"error": {"code": "rate_limit_exceeded"}}
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.agents.llm.get_settings", lambda: type(
        "S", (), {"groq_api_key": "test-key", "groq_model": "test-model"}
    )())
    return LLMClient()


@pytest.mark.parametrize("status_code", [429, 413])
def test_a_quota_or_size_failure_becomes_an_LLMError(client, monkeypatch, status_code):
    """The contract every caller relies on: whatever the provider does, what
    comes out of this module is an LLMError subclass."""
    def _boom(**_kwargs):
        raise _status_error(status_code)

    monkeypatch.setattr(client._client.chat.completions, "create", _boom)

    with pytest.raises(LLMOverloadedError) as exc_info:
        client.complete_json(system="s", user="u")

    # LLMOverloadedError is an LLMError, which is what the fallbacks catch.
    assert isinstance(exc_info.value, LLMError)


def test_the_message_is_something_a_user_can_read(client, monkeypatch):
    """It reaches real screens, so it must not be a stack trace or a raw
    provider string mentioning organization ids and token counts."""
    monkeypatch.setattr(
        client._client.chat.completions, "create", lambda **_k: (_ for _ in ()).throw(_status_error(429))
    )

    with pytest.raises(LLMOverloadedError) as exc_info:
        client.complete_json(system="s", user="u")

    message = str(exc_info.value)
    assert "usage limit" in message
    assert "org_" not in message
    assert "Traceback" not in message


def test_other_provider_errors_still_retry_then_fail_as_LLMError(client, monkeypatch):
    """A 500 is worth retrying; a spent quota is not. Both must still leave
    this module as an LLMError rather than a provider exception."""
    calls = {"n": 0}

    def _boom(**_kwargs):
        calls["n"] += 1
        raise _status_error(500)

    monkeypatch.setattr(client._client.chat.completions, "create", _boom)

    with pytest.raises(LLMError):
        client.complete_json(system="s", user="u", max_retries=2)

    assert calls["n"] == 3  # retried, unlike the quota case


def test_a_quota_failure_is_not_retried(client, monkeypatch):
    """Retrying a spent daily quota sends the same request against a limit
    that cannot refill mid-loop - it burns latency for a guaranteed failure."""
    calls = {"n": 0}

    def _boom(**_kwargs):
        calls["n"] += 1
        raise _status_error(429)

    monkeypatch.setattr(client._client.chat.completions, "create", _boom)

    with pytest.raises(LLMOverloadedError):
        client.complete_json(system="s", user="u", max_retries=2)

    assert calls["n"] == 1
