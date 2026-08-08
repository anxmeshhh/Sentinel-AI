"""Outlook Calendar workspace: writes through the Action Registry.

The properties worth protecting are the ones about consequence:
  * attendees turn a private write into invitations, and the risk must escalate
    to say so - reusing the rule the Google calendar action already had;
  * an edit is genuinely undoable because the PREVIOUS values are captured
    before anything changes;
  * cancelling is irreversible and offers no undo, because attendees were told.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.action_registry import REGISTRY, validate_params

NOW = datetime.now(timezone.utc)
CAL_ACTIONS = ("outlook.create_event", "outlook.update_event", "outlook.cancel_event")


@pytest.mark.parametrize("key", CAL_ACTIONS)
def test_every_calendar_write_is_external_and_confirmed(key):
    spec = REGISTRY[key]
    assert spec.external is True
    assert spec.needs_approval is True
    assert spec.verify is not None
    assert spec.available is True


def test_attendees_escalate_create_from_medium_to_high():
    """An event for yourself is a private write; the same event with attendees
    sends each of them an invitation, which is a different thing."""
    spec = REGISTRY["outlook.create_event"]
    base = {"title": "Deploy", "start": NOW.isoformat(), "end": (NOW + timedelta(hours=1)).isoformat()}
    solo = validate_params(spec, base)
    group = validate_params(spec, {**base, "attendee_emails": ["a@b.com"]})
    assert spec.effective_risk(solo).value == "medium"
    assert spec.effective_risk(group).value == "high"


def test_attendees_escalate_an_edit_too():
    spec = REGISTRY["outlook.update_event"]
    quiet = validate_params(spec, {"event_id": "e1", "title": "New title"})
    noisy = validate_params(spec, {"event_id": "e1", "attendee_emails": ["a@b.com"]})
    assert spec.effective_risk(quiet).value == "medium"
    assert spec.effective_risk(noisy).value == "high"


def test_create_and_update_are_undoable_but_cancel_is_not():
    """The three writes make three different promises, and the absence of a
    compensation is what makes IRREVERSIBLE real."""
    assert REGISTRY["outlook.create_event"].compensate is not None
    assert REGISTRY["outlook.create_event"].reversibility.value == "compensatable"
    assert REGISTRY["outlook.update_event"].compensate is not None
    assert REGISTRY["outlook.update_event"].reversibility.value == "compensatable"

    cancel = REGISTRY["outlook.cancel_event"]
    assert cancel.compensate is None          # no undo button can be offered
    assert cancel.reversibility.value == "irreversible"
    assert cancel.risk.value == "high"
    assert cancel.autonomy_eligible is False


def test_previews_name_the_consequence():
    create = REGISTRY["outlook.create_event"]
    p = create.preview(validate_params(create, {
        "title": "Deploy review", "start": NOW.isoformat(),
        "end": (NOW + timedelta(hours=1)).isoformat(), "attendee_emails": ["a@b.com", "c@d.com"],
    }))
    assert p["notifies"] is True and "2 attendee" in p["warning"]
    assert p["attendees"] == ["a@b.com", "c@d.com"]

    cancel = REGISTRY["outlook.cancel_event"]
    pc = cancel.preview(validate_params(cancel, {"event_id": "e1", "title": "Deploy", "attendee_count": 3}))
    assert pc["irreversible"] is True
    assert "notifies 3 attendee" in pc["warning"] and "cannot be recalled" in pc["warning"]


def test_a_solo_cancel_still_says_it_cannot_be_undone():
    cancel = REGISTRY["outlook.cancel_event"]
    p = cancel.preview(validate_params(cancel, {"event_id": "e1", "title": "Focus time", "attendee_count": 0}))
    assert "cannot be undone" in p["warning"]


def test_invalid_attendee_addresses_are_rejected():
    for key in ("outlook.create_event", "outlook.update_event"):
        spec = REGISTRY[key]
        params = {"event_id": "e1", "title": "x", "start": NOW.isoformat(),
                  "end": (NOW + timedelta(hours=1)).isoformat(), "attendee_emails": ["nope"]}
        with pytest.raises(Exception):
            validate_params(spec, params)


def test_update_compensation_requires_the_recorded_previous_values():
    """Undo is only offered because the previous state was captured; without it
    the compensation must refuse rather than guess."""
    from app.services.action_registry import ActionRejected

    class _Action:
        result: dict = {"event_id": "e1"}  # no `previous`

    with pytest.raises(ActionRejected):
        REGISTRY["outlook.update_event"].compensate(None, _Action())


def test_calendar_service_is_mapped_for_the_intelligence_rail():
    from app.api.routes.workspace import SERVICE_PROVIDERS
    from app.models.connection import Provider

    assert SERVICE_PROVIDERS["microsoft_calendar"] == (Provider.MICROSOFT_OUTLOOK_CALENDAR,)
