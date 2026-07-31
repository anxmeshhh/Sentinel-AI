"""Slack user id -> name resolution: cached, and never able to break a sync."""

from app.services import slack_users


def test_humanize_rewrites_mention_tokens():
    m = {"U1": "jess", "U2": "raj"}
    assert slack_users.humanize("hey <@U1> and <@U2>", m) == "hey @jess and @raj"
    # An unknown id is left as an id, not dropped.
    assert slack_users.humanize("cc <@U9>", m) == "cc @U9"
    assert slack_users.humanize("", m) == ""
    assert slack_users.humanize(None, m) == ""


def test_name_for_falls_back_to_id():
    assert slack_users.name_for("U1", {"U1": "jess"}) == "jess"
    assert slack_users.name_for("U9", {"U1": "jess"}) == "U9"


class _Boom:
    def list_users(self):
        raise RuntimeError("slack down")


def test_directory_is_best_effort(monkeypatch):
    """A failed lookup must not raise - names just fall back to ids. Uses a
    unique team id so the module cache can't hide the failure."""
    slack_users._CACHE.pop("T-boom", None)
    assert slack_users.directory(_Boom(), "T-boom") == {}


class _Ok:
    calls = 0

    def list_users(self):
        _Ok.calls += 1
        return [{"id": "U1", "name": "jess"}]


def test_directory_caches_per_team():
    _Ok.calls = 0
    slack_users._CACHE.pop("T-cache", None)
    c = _Ok()
    assert slack_users.directory(c, "T-cache") == {"U1": "jess"}
    slack_users.directory(c, "T-cache")  # second call hits the cache
    assert _Ok.calls == 1
