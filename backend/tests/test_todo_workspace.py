"""Microsoft To Do workspace: writes through the Action Registry.

A task list is private state, so nothing here notifies anyone - which is why
these are the gentlest writes in the registry AND why every one of them has a
real inverse. The tests below pin down that every undo is backed by something
recorded, never by a hopeful re-derivation.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.action_registry import ActionRejected, REGISTRY, validate_params

NOW = datetime.now(timezone.utc)
TODO_ACTIONS = ("todo.create_task", "todo.update_task", "todo.complete_task", "todo.delete_task")


@pytest.mark.parametrize("key", TODO_ACTIONS)
def test_every_todo_write_is_external_confirmed_verified_and_undoable(key):
    spec = REGISTRY[key]
    assert spec.external is True          # it changes the real Microsoft account
    assert spec.needs_approval is True    # so it is previewed and confirmed
    assert spec.verify is not None        # and read back from Microsoft
    assert spec.compensate is not None    # and every one can be put back
    assert spec.reversibility.value == "compensatable"
    assert spec.available is True


def test_delete_is_riskier_than_the_rest():
    """Deleting loses state the others only change, and the restore is a new
    task rather than the original - so it is priced higher."""
    assert REGISTRY["todo.delete_task"].risk.value == "medium"
    for key in ("todo.create_task", "todo.update_task", "todo.complete_task"):
        assert REGISTRY[key].risk.value == "low"


def test_importance_is_validated_against_a_known_set():
    spec = REGISTRY["todo.create_task"]
    with pytest.raises(Exception):
        validate_params(spec, {"list_id": "L1", "title": "x", "importance": "urgent"})
    ok = validate_params(spec, {"list_id": "L1", "title": "x", "importance": "HIGH"})
    assert ok.importance == "high"  # normalized, not merely accepted


def test_previews_say_what_will_change():
    create = REGISTRY["todo.create_task"]
    p = create.preview(validate_params(create, {
        "list_id": "L1", "title": "Ship release", "due_at": NOW.isoformat(), "importance": "high",
    }))
    assert "Ship release" in p["summary"] and "high importance" in p["summary"]

    complete = REGISTRY["todo.complete_task"]
    done = complete.preview(validate_params(complete, {"list_id": "L1", "task_id": "t1", "completed": True, "title": "Ship"}))
    reopen = complete.preview(validate_params(complete, {"list_id": "L1", "task_id": "t1", "completed": False, "title": "Ship"}))
    assert done["summary"].startswith("Complete") and reopen["summary"].startswith("Reopen")


def test_clearing_a_due_date_is_distinct_from_leaving_it_alone():
    """`None` is a real edit here, so the params carry an explicit flag rather
    than overloading absence."""
    spec = REGISTRY["todo.update_task"]
    cleared = validate_params(spec, {"list_id": "L1", "task_id": "t1", "clear_due": True})
    assert cleared.clear_due is True
    p = spec.preview(cleared)
    assert "due date → cleared" in p["changes"]

    untouched = validate_params(spec, {"list_id": "L1", "task_id": "t1", "title": "New"})
    assert untouched.clear_due is False
    assert "due" not in " ".join(spec.preview(untouched)["changes"])


def test_delete_preview_is_honest_that_undo_makes_a_new_task():
    spec = REGISTRY["todo.delete_task"]
    p = spec.preview(validate_params(spec, {"list_id": "L1", "task_id": "t1", "title": "Ship"}))
    assert "recreates it from the recorded values as a new task" in p["warning"]


@pytest.mark.parametrize("key", ("todo.update_task", "todo.delete_task"))
def test_undo_refuses_when_the_snapshot_is_missing(key):
    """Both undos restore from values captured BEFORE the change. Without that
    snapshot they must refuse rather than invent a previous state."""
    class _Action:
        result: dict = {"list_id": "L1", "task_id": "t1"}  # no `previous`

    with pytest.raises(ActionRejected):
        REGISTRY[key].compensate(None, _Action())


def test_complete_undo_needs_no_snapshot_because_the_inverse_is_exact():
    """Completing has a perfect inverse, so its compensation reads the intent
    from the original params rather than needing a recorded before-state."""
    spec = REGISTRY["todo.complete_task"]
    assert spec.compensate is not None
    import inspect

    src = inspect.getsource(spec.compensate)
    assert "not params.completed" in src


def test_todo_service_is_mapped_for_the_intelligence_rail():
    from app.api.routes.workspace import SERVICE_PROVIDERS
    from app.models.connection import Provider

    assert SERVICE_PROVIDERS["microsoft_todo"] == (Provider.MICROSOFT_TODO,)


def test_task_detectors_are_untouched_by_the_workspace():
    """The workspace must not have redesigned the Intelligence Core: the TASK
    detectors still read signals and remain provider-agnostic."""
    import inspect

    from app.services import attention_engine as ae

    src = inspect.getsource(ae._detect_overdue_tasks)
    assert "SignalType.TASK" in inspect.getsource(ae._open_task_signals)
    assert "MICROSOFT" not in src.upper()
