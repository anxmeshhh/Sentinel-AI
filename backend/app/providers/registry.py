"""One place that says what each provider *is*.

Before this, the same four providers were described by four separate literals
in four different modules:

    INGESTABLE_PROVIDERS      api/routes/integrations.py
    _LIVE_QUERY_PROVIDERS     services/channel_readiness.py
    RESOURCE_SCOPED_PROVIDERS services/channel_briefing.py
    PROVIDER_LABEL            (again, in the frontend)

Nothing forced them to agree, and the first two are logical complements - a
provider is either ingested into Signals or queried live, never both. They
drifted exactly once, which is all it took: Google Drive was added to neither
set, so `last_synced_at` stayed NULL forever, readiness reported `syncing`
forever, and channel setup could never reach complete. The bug was invisible
in tests because each module was individually self-consistent.

A ProviderSpec makes that class of bug unrepresentable: `ingests` and
`live_query` are one field with two values, and a provider that declares
neither fails at import.

## What this is not

Not a plugin framework, and deliberately not a place for API clients or
fetch logic. Those stay in `app/integrations/`, where each provider's real
differences (pagination, rate limits, auth dance) belong. This registry holds
only the facts the *rest of the application* needs in order to treat a
provider generically - which is a small, stable set, and every field here
earned its place by already existing as a scattered literal.

Adding a provider means: one entry here, one client in `app/integrations/`,
one ingest handler (if it ingests), one enum member. Nothing else in the
codebase enumerates providers by hand any more.
"""

import enum
from dataclasses import dataclass

from app.models.connection import Provider
from app.models.signal import SignalType


class Retrieval(str, enum.Enum):
    """How a provider's data reaches Sentinel.

    INGESTED  - polled into Signals on a schedule, and everything downstream
                (attention detection, feed, insights) reads those rows.
    LIVE      - never stored; queried at request time against the provider.
                Drive is the standing example: caching a user's whole file
                tree would be both enormous and a data-retention liability
                for content Sentinel only needs momentarily.

    A provider is one or the other. This is the distinction that used to be
    two independent sets, and this is the field that keeps them consistent.
    """

    INGESTED = "ingested"
    LIVE = "live"


class AuthKind(str, enum.Enum):
    OAUTH = "oauth"  # user consents; refresh token stored; revocation observable
    PAT = "pat"  # a pasted long-lived token; no refresh, no revocation signal


@dataclass(frozen=True)
class ProviderSpec:
    key: Provider
    label: str
    retrieval: Retrieval
    auth: AuthKind

    # Signal types this provider can produce. Empty for LIVE providers, which
    # write no Signals at all outside the seeded demo workspace.
    signal_types: tuple[SignalType, ...] = ()

    # Whether a connection to this provider grants access to many separately
    # addressable things (files, pages, boards) rather than one bounded scope
    # (a mailbox, a repo). Resource-scoped providers are fail-closed: sharing
    # the connection grants nothing until specific resources are allow-listed.
    resource_scoped: bool = False

    @property
    def ingests(self) -> bool:
        return self.retrieval is Retrieval.INGESTED

    @property
    def live_query(self) -> bool:
        return self.retrieval is Retrieval.LIVE

    @property
    def revocation_observable(self) -> bool:
        """Can Sentinel tell when this connection has died?

        Only via a refresh that actually fails, which needs a refresh token -
        so PAT providers cannot report `expired` honestly and will keep
        reporting `ready` with a dead token. Stated here rather than
        rediscovered per provider; see channel_readiness for how it's used.
        """
        return self.auth is AuthKind.OAUTH


PROVIDERS: dict[Provider, ProviderSpec] = {
    spec.key: spec
    for spec in (
        ProviderSpec(
            key=Provider.GITHUB,
            label="GitHub",
            retrieval=Retrieval.INGESTED,
            # Still a pasted token. Phase C replaces this with a GitHub OAuth
            # App, at which point `expired` becomes reportable for GitHub too.
            auth=AuthKind.PAT,
            signal_types=(SignalType.PR, SignalType.REVIEW_SUBMITTED, SignalType.COMMIT, SignalType.ISSUE),
        ),
        ProviderSpec(
            key=Provider.GMAIL,
            label="Gmail",
            retrieval=Retrieval.INGESTED,
            auth=AuthKind.OAUTH,
            signal_types=(SignalType.EMAIL,),
        ),
        ProviderSpec(
            key=Provider.GOOGLE_CALENDAR,
            label="Google Calendar",
            retrieval=Retrieval.INGESTED,
            auth=AuthKind.OAUTH,
            signal_types=(SignalType.CALENDAR_EVENT,),
        ),
        ProviderSpec(
            key=Provider.GOOGLE_DRIVE,
            label="Google Drive",
            retrieval=Retrieval.LIVE,
            auth=AuthKind.OAUTH,
            # A Drive connection reaches every file the account can see, so an
            # admin's allow-list is the only thing that says which documents a
            # channel may use.
            resource_scoped=True,
        ),
    )
}


def spec_for(provider: Provider) -> ProviderSpec:
    return PROVIDERS[provider]


# Every Provider must be described. A new enum member without a spec is a
# provider the rest of the app cannot reason about - caught at import rather
# than as a KeyError somewhere downstream at request time.
_missing = [p for p in Provider if p not in PROVIDERS]
if _missing:
    raise RuntimeError(f"Provider(s) missing a ProviderSpec: {[p.value for p in _missing]}")


INGESTABLE_PROVIDERS = frozenset(p for p, s in PROVIDERS.items() if s.ingests)
LIVE_QUERY_PROVIDERS = frozenset(p for p, s in PROVIDERS.items() if s.live_query)
RESOURCE_SCOPED_PROVIDERS = frozenset(p for p, s in PROVIDERS.items() if s.resource_scoped)
PROVIDER_BY_NAME: dict[str, Provider] = {p.value: p for p in Provider}
