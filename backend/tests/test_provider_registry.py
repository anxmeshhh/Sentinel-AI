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


def test_no_two_providers_claim_the_same_signal_type():
    """Signal types identify what a row *is*, and detectors read them without
    checking the provider. Two providers producing SignalType.EMAIL would
    make every email detector silently provider-ambiguous - worth a decision
    rather than a surprise, so this fails until someone makes one."""
    seen: dict[SignalType, str] = {}
    for spec in PROVIDERS.values():
        for signal_type in spec.signal_types:
            assert signal_type not in seen, (
                f"{spec.label} and {seen[signal_type]} both produce {signal_type.value}"
            )
            seen[signal_type] = spec.label


def test_resource_scoped_providers_are_the_ones_that_reach_many_things():
    """Fail-closed depends on this being right: a resource-scoped connection
    grants nothing until specific resources are allow-listed. Drive reaches
    every file in an account; a mailbox and a repo are each one bounded
    scope."""
    assert RESOURCE_SCOPED_PROVIDERS == {Provider.GOOGLE_DRIVE}
    assert spec_for(Provider.GMAIL).resource_scoped is False
    assert spec_for(Provider.GITHUB).resource_scoped is False


def test_revocation_is_only_observable_for_oauth_providers():
    """Why an expired GitHub token still reports `ready`. Detecting a dead
    connection requires a refresh that fails, which requires a refresh token -
    a pasted PAT has none. Stated once here instead of being rediscovered
    per provider."""
    assert spec_for(Provider.GITHUB).auth is AuthKind.PAT
    assert spec_for(Provider.GITHUB).revocation_observable is False

    for provider in (Provider.GMAIL, Provider.GOOGLE_CALENDAR, Provider.GOOGLE_DRIVE):
        assert spec_for(provider).revocation_observable is True


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
