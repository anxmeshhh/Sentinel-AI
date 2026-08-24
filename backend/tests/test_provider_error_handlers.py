"""A revoked token is not a Sentinel bug, and must not be reported as one.

Provider auth failures are the single most likely thing to go wrong in
production - tokens expire and get revoked - and every one of them used to
surface as the generic catch-all 500: "Something went wrong on Sentinel's
side." That is both wrong and useless. Nothing went wrong on Sentinel's side,
and the one thing the person could do about it went unsaid.

These handlers are registered ONE CLASS AT A TIME on purpose. Starlette
resolves a handler by walking `type(exc).__mro__` and looking each class up as
a dict key, so registering a tuple stores the tuple itself as the key and the
handler never fires - silently, which is the worst way for error handling to be
wrong. The first test below is what catches that regression.
"""

import pytest
from fastapi.testclient import TestClient

from app.integrations.github_auth import GitHubAuthError
from app.integrations.google_auth import GoogleAuthError
from app.integrations.graph_client import GraphError
from app.integrations.microsoft_auth import MicrosoftAuthError
from app.integrations.slack_auth import SlackAuthError
from app.integrations.slack_client import SlackClientError
from app.integrations.zoom_auth import ZoomAuthError
from app.integrations.zoom_client import ZoomError, ZoomPlanError
from app.main import app

AUTH_ERRORS = [GoogleAuthError, MicrosoftAuthError, ZoomAuthError, SlackAuthError, GitHubAuthError]
API_ERRORS = [GraphError, SlackClientError, ZoomError]


@pytest.mark.parametrize("exc", AUTH_ERRORS + API_ERRORS)
def test_every_provider_error_has_a_handler_registered_by_class(exc):
    """The registration bug, asserted directly: a tuple key would leave every
    one of these unregistered while looking correct in the source."""
    assert exc in app.exception_handlers, f"{exc.__name__} has no handler - was it registered as a tuple?"


def test_a_subclassed_provider_error_still_resolves():
    """ZoomPlanError subclasses ZoomError. Starlette walks the MRO, so the
    parent's handler covers it - asserted so a future subclass is not assumed
    to be covered without checking."""
    assert any(cls in app.exception_handlers for cls in ZoomPlanError.__mro__)


def test_an_expired_token_says_to_reconnect_rather_than_blaming_sentinel():
    @app.get("/__test_auth_error")
    def _raise():
        raise GoogleAuthError("Google token refresh failed: 400")

    response = TestClient(app, raise_server_exceptions=False).get("/__test_auth_error")

    # 502, not 500: the request was fine, an upstream dependency was not.
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "reconnect" in detail.lower()
    # The old generic message must not be what a user sees for this.
    assert "went wrong on Sentinel's side" not in detail


def test_an_unreachable_provider_is_reported_as_the_providers_problem():
    @app.get("/__test_api_error")
    def _raise():
        raise GraphError("Graph returned 503")

    response = TestClient(app, raise_server_exceptions=False).get("/__test_api_error")

    assert response.status_code == 502
    assert "provider could not be reached" in response.json()["detail"].lower()


def test_the_raw_provider_error_is_never_leaked_to_the_caller():
    """Provider messages can carry tokens, ids and internal URLs. They are
    logged, never returned."""
    @app.get("/__test_leak")
    def _raise():
        raise GoogleAuthError("refresh failed for token ya29.SECRET-VALUE")

    response = TestClient(app, raise_server_exceptions=False).get("/__test_leak")

    assert "SECRET-VALUE" not in response.text
    assert "ya29" not in response.text
