"""OneDrive and OneNote workspaces: writes through the Action Registry.

These two services are where "honest undo" gets hardest, so that is what the
tests are about: which writes can genuinely be taken back, which cannot, and
that the ones which can are backed by something actually recorded first.
"""

import pytest

from app.services.action_registry import ActionRejected, REGISTRY, validate_params

DRIVE_ACTIONS = ("onedrive.create_folder", "onedrive.upload_text", "onedrive.rename_item",
                 "onedrive.move_item", "onedrive.delete_item")
NOTE_ACTIONS = ("onenote.create_page", "onenote.append_page")


@pytest.mark.parametrize("key", DRIVE_ACTIONS + NOTE_ACTIONS)
def test_every_write_is_external_confirmed_and_verified(key):
    spec = REGISTRY[key]
    assert spec.external is True
    assert spec.needs_approval is True
    assert spec.verify is not None
    assert spec.available is True


def test_only_drive_delete_is_irreversible_and_it_says_why():
    """Everything else can be taken back. Deleting cannot, because Graph moves
    the item to the OneDrive recycle bin and offers this API no way back."""
    delete = REGISTRY["onedrive.delete_item"]
    assert delete.reversibility.value == "irreversible"
    assert delete.compensate is None          # so no undo button is offered
    assert delete.risk.value == "medium"      # priced above the rest
    assert delete.autonomy_eligible is False

    for key in set(DRIVE_ACTIONS + NOTE_ACTIONS) - {"onedrive.delete_item"}:
        spec = REGISTRY[key]
        assert spec.compensate is not None, key
        assert spec.reversibility.value == "compensatable", key


def test_delete_preview_tells_the_user_where_it_goes():
    spec = REGISTRY["onedrive.delete_item"]
    p = spec.preview(validate_params(spec, {"item_id": "i1", "name": "Report.docx"}))
    assert p["irreversible"] is True
    assert "recycle bin" in p["warning"]
    assert "Sentinel cannot restore it" in p["warning"]

    folder = spec.preview(validate_params(spec, {"item_id": "i1", "name": "Docs", "is_folder": True}))
    # Deleting a folder takes its contents, and the preview says so.
    assert "everything in it" in folder["summary"]


def test_file_and_folder_names_reject_path_characters():
    for key, field in (("onedrive.create_folder", "name"), ("onedrive.rename_item", "new_name")):
        spec = REGISTRY[key]
        base = {"item_id": "i1", "name": "ok", "new_name": "ok"}
        bad = {**base, field: 'bad/name'}
        with pytest.raises(Exception):
            validate_params(spec, bad)


def test_upload_is_capped_and_text_only():
    """Content travels as an action parameter, so this is deliberately for typed
    documents rather than a general file-transfer path."""
    from app.services.action_registry import MAX_UPLOAD_CHARS

    spec = REGISTRY["onedrive.upload_text"]
    with pytest.raises(Exception):
        validate_params(spec, {"name": "big.txt", "content": "x" * (MAX_UPLOAD_CHARS + 1)})
    ok = validate_params(spec, {"name": "notes.txt", "content": "hello"})
    assert ok.name == "notes.txt"


@pytest.mark.parametrize("key,missing", [
    ("onedrive.rename_item", "previous_name"),
    ("onedrive.move_item", "previous_parent_id"),
    ("onenote.append_page", "previous_html"),
])
def test_undo_refuses_when_the_snapshot_is_missing(key, missing):
    """Each of these undos restores from a value captured BEFORE the change.
    Without it they must refuse rather than invent a previous state."""
    class _Action:
        result: dict = {"item_id": "i1", "page_id": "p1"}

    with pytest.raises(ActionRejected):
        REGISTRY[key].compensate(None, _Action())


def test_append_records_whether_undo_was_even_possible():
    """A page too large to snapshot loses its undo - the action row says so
    explicitly rather than leaving it to be discovered at undo time."""
    import inspect

    src = inspect.getsource(REGISTRY["onenote.append_page"].execute)
    assert "undo_available" in src
    assert "MAX_UNDO_SNAPSHOT_CHARS" in src


def test_services_are_mapped_for_the_intelligence_rail():
    from app.api.routes.workspace import SERVICE_PROVIDERS
    from app.models.connection import Provider

    assert SERVICE_PROVIDERS["microsoft_onedrive"] == (Provider.MICROSOFT_ONEDRIVE,)
    assert SERVICE_PROVIDERS["microsoft_onenote"] == (Provider.MICROSOFT_ONENOTE,)


def test_read_routes_never_reach_a_graph_write():
    """The workspace router reads; the Action Registry writes. Structural, so it
    cannot drift into a second unaudited write path."""
    import app.api.routes.workspace as mod

    source = open(mod.__file__, encoding="utf-8").read()
    for forbidden in ("create_folder", "upload_text_file", "rename_item", "move_item",
                      "delete_item", "create_page", "patch_page", "delete_page"):
        assert forbidden not in source, f"{forbidden} must only be reachable from the Action Registry"
