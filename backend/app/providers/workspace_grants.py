"""Workspace grants - one OAuth grant that fans out into a fixed set of child
service-connections.

Some providers are a single bounded thing (a GitHub repo, a Slack channel):
each becomes its own Connection, chosen one at a time. Others are a *workspace*
- one account grant that reaches several fixed services at once (Google:
Calendar + Gmail + Drive; Microsoft 365: Outlook Mail + Calendar + ...). Those
share one token and one account identity, and provisioning them is identical
apart from the list of services - which is exactly what this declares.

This is the N=2 generalization: the moment a second workspace-provider (Microsoft)
exists, the Google-specific provisioning becomes one generic loop over a grant's
services (see services/grants.py). Adding services to a grant later (Sprint 2/3)
is a one-line change here.
"""

from dataclasses import dataclass

from app.models.connection import Provider


@dataclass(frozen=True)
class WorkspaceGrantSpec:
    key: str  # "google" | "microsoft"
    label: str
    # (provider, resource-label) pairs. The label is stored as Connection.repo,
    # the human-facing name of the child service within the grant.
    services: tuple[tuple[Provider, str], ...]

    @property
    def providers(self) -> tuple[Provider, ...]:
        return tuple(p for p, _ in self.services)


GOOGLE_GRANT = WorkspaceGrantSpec(
    key="google",
    label="Google Workspace",
    services=(
        (Provider.GOOGLE_CALENDAR, "calendar"),
        (Provider.GMAIL, "gmail"),
        (Provider.GOOGLE_DRIVE, "drive"),
    ),
)

# Sprint 1: mail + calendar. Sprint 2 adds Teams/OneDrive/SharePoint/OneNote;
# Sprint 3 adds Planner/To Do. Extending this tuple is the only change needed
# to provision more of the same grant.
MICROSOFT_GRANT = WorkspaceGrantSpec(
    key="microsoft",
    label="Microsoft 365",
    services=(
        (Provider.MICROSOFT_OUTLOOK_MAIL, "mail"),
        (Provider.MICROSOFT_OUTLOOK_CALENDAR, "calendar"),
    ),
)

# Providers whose per-account replacement should also clear cached mail
# summaries (keyed by workspace+message), since a new mailbox invalidates them.
MAIL_PROVIDERS: frozenset[Provider] = frozenset({Provider.GMAIL, Provider.MICROSOFT_OUTLOOK_MAIL})
