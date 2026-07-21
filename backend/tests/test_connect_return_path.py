"""The post-OAuth return path must never leave this app.

Connecting from inside a channel returns the admin to that channel, which
means a caller-supplied path ends up in a redirect. Accepting it verbatim
would be an open redirect: a crafted connect link could bounce a user to
an external site immediately after an OAuth flow, wearing Sentinel's
trust at the exact moment they're primed to accept it.
"""

import pytest

from app.api.routes.integrations import _safe_return_path


@pytest.mark.parametrize(
    "path",
    [
        "/channels/abc-123",
        "/connections/google",
        "/",
        "/attention?state=new",
    ],
)
def test_internal_paths_are_preserved(path):
    assert _safe_return_path(path) == path


@pytest.mark.parametrize(
    "hostile",
    [
        "https://evil.example.com/steal",
        "http://evil.example.com",
        "//evil.example.com",  # protocol-relative - browsers treat as external
        "javascript:alert(1)",
        "evil.example.com",
        "",
        None,
    ],
)
def test_external_and_malformed_targets_fall_back_to_dashboard(hostile):
    assert _safe_return_path(hostile) == "/"
