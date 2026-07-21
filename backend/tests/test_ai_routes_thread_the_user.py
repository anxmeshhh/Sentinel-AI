"""Every AI route must thread the acting user into the orchestrator.

Phase A made `_get_connection` fail closed when `user_id` is None - the
right behaviour for isolation, with a failure mode this file exists to
prevent: a route that forgets to pass the user doesn't leak, it goes
*blind*. The workspace-wide AI command shipped exactly that way and spent
the whole period since the per-user migration answering "gmail not
connected" against a fully connected account, while the model wrapped the
error in polite prose. The suite stayed green because nothing pinned the
threading.

These tests are deliberately structural: they assert the route signatures
declare the current user and that each orchestrator call forwards it, so
the next route added without `user_id=` fails CI instead of failing
silently in production.
"""

import inspect
import re

from app.api.routes import channel_ai, connections_ai


def _source(fn) -> str:
    return inspect.getsource(fn)


def test_workspace_ai_routes_declare_the_current_user():
    for route in (connections_ai.google_command, connections_ai.google_command_stream, connections_ai.google_command_execute):
        assert "user" in inspect.signature(route).parameters, f"{route.__name__} has no current-user dependency"


def test_workspace_ai_routes_forward_user_id_to_the_orchestrator():
    assert re.search(r"run_command\(.*user_id=user\.id", _source(connections_ai.google_command))
    assert re.search(r"run_command_stream\(.*user_id=user\.id", _source(connections_ai.google_command_stream))
    assert re.search(r"execute_planned_action\(.*user_id=user\.id", _source(connections_ai.google_command_execute))


def test_channel_ai_routes_forward_user_id_to_the_orchestrator():
    assert re.search(r"run_command\(.*user_id=user\.id", _source(channel_ai.channel_ai_command))
    assert re.search(r"run_command_stream\(.*user_id=user\.id", _source(channel_ai.channel_ai_command_stream))
    # The confirm-execute leg was ALSO missing the user - a confirmed
    # calendar action in a channel failed closed at the connection lookup.
    assert re.search(r"execute_planned_action\(.*user_id=user\.id", _source(channel_ai.channel_ai_command_execute))
