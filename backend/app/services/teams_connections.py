"""One Microsoft 365 account, many monitored Teams channels.

Teams' vocabulary over the shared provider_account helper - the same layer
GitHub and Slack use, so nothing about multi-resource management is written a
third time. A monitored channel is a full Connection row:

    org           the team (group) id - which team the channel belongs to
    repo          the channel id, stable across renames
    display_name  the human name, rendered "Team / Channel"
    github_login  the Microsoft account identity (the generic account-identity
                  column, named for the provider that needed it first)

The token comes from the Microsoft grant: Teams is an anchor provider on
MICROSOFT_GRANT, so connecting Microsoft 365 once already created the anchor
row that holds it (see providers/workspace_grants.py).

NOTE ON NAMING: `Team` in this codebase is Sentinel's own channel concept
(models/team.py, the `channel:{team_id}` scope). Microsoft Teams deliberately
introduces no model of its own - a monitored channel is just a Connection - so
the two never collide.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.connection import Connection, Provider
from app.services import provider_account
from app.services.provider_account import ProviderAccountError


class TeamsAccountError(ProviderAccountError):
    pass


def teams_account(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Connection | None:
    """This user's Teams anchor/rows in this workspace (they share the Microsoft
    grant's token), or None if Microsoft 365 was never connected."""
    rows = provider_account.account_connections(session, workspace_id, user_id, Provider.MICROSOFT_TEAMS)
    return rows[0] if rows else None


def monitored_channels(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> list[Connection]:
    return provider_account.monitored_resources(session, workspace_id, user_id, Provider.MICROSOFT_TEAMS)


def add_channel(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    team_id: str,
    team_name: str,
    channel_id: str,
    channel_name: str,
) -> Connection:
    """Start monitoring one Teams channel under the connected Microsoft account.

    `org` holds the *team* id rather than the account, because every Graph call
    for a channel needs its team id - keeping it on the row is what lets
    ingestion address the channel without a second lookup.
    """
    account = provider_account.account_connections(session, workspace_id, user_id, Provider.MICROSOFT_TEAMS)
    if not account:
        raise TeamsAccountError("Connect Microsoft 365 first")
    return provider_account.add_resource(
        session, workspace_id=workspace_id, user_id=user_id, provider=Provider.MICROSOFT_TEAMS,
        org=team_id, repo=channel_id, display_name=f"{team_name} / {channel_name}",
    )
