"""The provider registry is the thing that keeps provider facts consistent.

These tests are mostly about the *next* provider rather than the four that
exist: the registry earns its place only if adding GitHub OAuth, Slack or
Jira cannot reintroduce the drift it was built to prevent.

The drift in question is real and shipped: `INGESTABLE_PROVIDERS` and
`_LIVE_QUERY_PROVIDERS` were independent literals in different modules, and
Google Drive was in neither. `last_synced_at` therefore stayed NULL forever,
readiness reported `syncing` forever, and channel setup could never complete.
Every module was individually self-consistent, so nothing failed.
"""

import pytest

from app.models.connection import Provider
from app.models.signal import SignalType
from app.providers.registry import (
    INGESTABLE_PROVIDERS,
    LIVE_QUERY_PROVIDERS,
    PROVIDERS,
    RESOURCE_SCOPED_PROVIDERS,
    AuthKind,
    ProviderSpec,
    Retrieval,
    spec_for,
)


def test_every_provider_is_described():
    """A Provider without a spec is one the rest of the app cannot reason
    about. The registry raises at import if this is ever false; this test
    states the invariant where a reader will find it."""
    assert set(PROVIDERS) == set(Provider)


def test_ingested_and_live_partition_every_provider():
    """The bug, made structurally impossible. These were two hand-maintained
    sets that had to be exact complements and were not; they are now one
    field with two values, so a provider cannot be in both or in neither."""
    assert INGESTABLE_PROVIDERS.isdisjoint(LIVE_QUERY_PROVIDERS)
    assert INGESTABLE_PROVIDERS | LIVE_QUERY_PROVIDERS == set(Provider)


def test_drive_is_live_and_would_not_get_stuck_syncing():
    """The specific regression. Drive is queried live, so readiness must not
    wait for a first sync that never comes."""
    spec = spec_for(Provider.GOOGLE_DRIVE)

    assert spec.live_query is True
    assert spec.ingests is False
    assert Provider.GOOGLE_DRIVE not in INGESTABLE_PROVIDERS


@pytest.mark.parametrize("provider", list(Provider))
def test_an_ingesting_provider_declares_what_it_produces(provider):
    """A provider that writes Signals must say which types, because the feed,
    insights and attention detectors are all written against those types. A
    live provider stores nothing and declares none."""
    spec = spec_for(provider)

    if spec.ingests:
        assert spec.signal_types, f"{spec.label} ingests but declares no signal types"
    else:
        assert spec.signal_types == ()


@pytest.mark.parametrize("provider", list(Provider))
def test_every_declared_signal_type_is_real(provider):
    for signal_type in spec_for(provider).signal_types:
        assert isinstance(signal_type, SignalType)


def test_signal_type_sharing_is_intentional_provider_reuse():
    """Detectors read SignalType, never the provider - which is exactly what lets
    a NEW provider reuse the whole Intelligence Core by producing an existing
    signal type (Outlook Mail -> EMAIL, Outlook Calendar -> CALENDAR_EVENT, so
    the Gmail/Calendar detectors fire unchanged). Sharing is therefore allowed -
    but only among declared twins; any OTHER overlap is an accident worth
    catching, so record a new intentional twin here or this fails."""
    intentional_twins: dict[SignalType, set[str]] = {
        SignalType.EMAIL: {"Gmail", "Outlook Mail"},
        # Zoom joins the calendar twins on purpose: a Zoom meeting IS a calendar
        # event that carries a join link, so normalizing it to CALENDAR_EVENT is
        # what lets the existing meeting detector - and the whole Intelligence
        # Core behind it - work with no Zoom-aware code anywhere downstream.
        SignalType.CALENDAR_EVENT: {"Google Calendar", "Outlook Calendar", "Zoom"},
        # Slack and Teams are the two chat providers, and they deliberately emit
        # the SAME conversation signals so the shared conversation detectors fire
        # for both without knowing which one produced them.
        SignalType.CHANNEL_ACTIVITY: {"Slack", "Microsoft Teams"},
        SignalType.MENTION: {"Slack", "Microsoft Teams"},
        SignalType.FLAGGED_MESSAGE: {"Slack", "Microsoft Teams"},
    }
    claimants: dict[SignalType, set[str]] = {}
    for spec in PROVIDERS.values():
        for signal_type in spec.signal_types:
            claimants.setdefault(signal_type, set()).add(spec.label)

    for signal_type, labels in claimants.items():
        if len(labels) > 1:
            assert labels == intentional_twins.get(signal_type), (
                f"Unexpected providers {labels} share {signal_type.value}; "
                f"if this is deliberate reuse, record it in intentional_twins."
            )


def test_resource_scoped_providers_are_the_ones_that_reach_many_things():
    """Fail-closed depends on this being right: a resource-scoped connection
    grants nothing until specific resources are allow-listed. Drive reaches
    every file in an account; a mailbox and a repo are each one bounded
    scope."""
    # The file/document stores: one grant reaches every item, so a channel must
    # allow-list specific resources before it sees any of them.
    assert RESOURCE_SCOPED_PROVIDERS == {
        Provider.GOOGLE_DRIVE, Provider.MICROSOFT_ONEDRIVE, Provider.MICROSOFT_ONENOTE,
    }
    # Bounded scopes are not resource-scoped: a mailbox, a repo, a chat channel
    # and a personal task list are each one thing the connection already names.
    assert spec_for(Provider.GMAIL).resource_scoped is False
    assert spec_for(Provider.GITHUB).resource_scoped is False
    assert spec_for(Provider.MICROSOFT_TODO).resource_scoped is False


def test_every_provider_can_now_report_its_own_death():
    """This test used to assert the opposite for GitHub, and the change is
    the point.

    While GitHub was a pasted PAT, Sentinel had no way to notice a revoked
    token: there was no refresh to fail and no credentials of its own to ask
    with, so a dead connection kept reporting `ready` and any channel
    depending on it looked healthy while returning nothing. The OAuth App
    closed that - it can ask GitHub directly whether a grant still stands
    (integrations/github_auth.py).

    No provider is PAT any more, so this asserts the property rather than the
    exception. If a future provider is added with PAT auth, the second half
    fails and forces the same question to be answered for it.
    """
    for provider in Provider:
        spec = spec_for(provider)
        assert spec.auth is AuthKind.OAUTH, f"{spec.label} is not OAuth"
        assert spec.revocation_observable is True

    # The rule that made the old GitHub case unavoidable, kept executable:
    # PAT auth still means revocation is undetectable, whoever adds one next.
    pat_like = ProviderSpec(
        key=Provider.GITHUB, label="Hypothetical PAT provider",
        retrieval=Retrieval.INGESTED, auth=AuthKind.PAT,
        signal_types=(SignalType.ISSUE,),
    )
    assert pat_like.revocation_observable is False


def test_labels_are_human_and_unique():
    labels = [s.label for s in PROVIDERS.values()]
    assert len(set(labels)) == len(labels)
    assert all(label and not label.islower() for label in labels)  # "Gmail", not "gmail"


# --- the consumers actually read from it -----------------------------------


def test_readiness_reads_live_query_from_the_registry():
    """Not a re-implementation: the module under test must resolve the fact
    through the registry, so a new live-query provider needs no edit there."""
    from app.models.connection import Connection
    from app.services.channel_readiness import ReadinessState, _state_for

    drive = Connection(provider=Provider.GOOGLE_DRIVE, org="a@x.com", repo="drive", encrypted_token="x")
    gmail = Connection(provider=Provider.GMAIL, org="a@x.com", repo="gmail", encrypted_token="x")

    # Neither has ever synced.
    assert _state_for(drive) == ReadinessState.READY  # nothing to wait for
    assert _state_for(gmail) == ReadinessState.SYNCING  # a first sync is coming


def test_briefing_reads_resource_scoping_from_the_registry():
    from app.services import channel_briefing

    assert channel_briefing.RESOURCE_SCOPED_PROVIDERS is RESOURCE_SCOPED_PROVIDERS


def test_integrations_route_reads_ingestability_from_the_registry():
    from app.api.routes import integrations

    assert integrations.INGESTABLE_PROVIDERS is INGESTABLE_PROVIDERS


def test_a_live_provider_refuses_ingestion_with_a_clear_reason():
    """"No handler for provider X" reads like an omission. It isn't one."""
    from app.models.connection import Connection
    from app.services.ingestion import ingest_connection

    drive = Connection(provider=Provider.GOOGLE_DRIVE, org="a@x.com", repo="drive", encrypted_token="x")

    with pytest.raises(ValueError, match="queried live"):
        ingest_connection(None, drive)
