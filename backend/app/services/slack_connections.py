"""One Slack workspace, many monitored channels.

Slack's vocabulary over the shared provider_account helper (the second-instance
refactor is now done - the multi-resource logic lives there, used by GitHub and
Slack alike). A monitored channel is a full Connection row: its `repo` holds the
channel *id* (stable across renames), its `display_name` the human "#name", and
`github_login` the Slack team id - the account identity that tells a reconnect
of a different workspace apart from a token refresh of the same one.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.connection import Connection, Provider
from app.services import provider_account
from app.services.provider_account import ProviderAccountError


class SlackAccountError(ProviderAccountError):
    pass


def slack_workspace(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Connection | None:
    """This user's Slack account in this workspace (any row - they share one bot
    token), or None. Used to reach the token and the team identity."""
    rows = provider_account.account_connections(session, workspace_id, user_id, Provider.SLACK)
    return rows[0] if rows else None


def monitored_channels(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> list[Connection]:
    return provider_account.monitored_resources(session, workspace_id, user_id, Provider.SLACK)


def connect_slack_workspace(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    team_id: str,
    team_name: str,
    encrypted_token: str,
) -> Connection:
    """Reconcile the Slack account after an OAuth round trip. The team id is the
    account identity; the team name is its display."""
    return provider_account.connect_account(
        session, workspace_id=workspace_id, user_id=user_id, provider=Provider.SLACK,
        account_identity=team_id, encrypted_token=encrypted_token, anchor_org=team_name,
    )


def add_channel(
    session: Session, *, workspace_id: uuid.UUID, user_id: uuid.UUID, channel_id: str, channel_name: str
) -> Connection:
    """Start monitoring one channel. `org` is the workspace name (shared by all
    the account's rows), `repo` the channel id, `display_name` the #name."""
    account = provider_account.account_connections(session, workspace_id, user_id, Provider.SLACK)
    if not account:
        raise SlackAccountError("Connect a Slack workspace first")
    team_name = account[0].org
    return provider_account.add_resource(
        session, workspace_id=workspace_id, user_id=user_id, provider=Provider.SLACK,
        org=team_name, repo=channel_id, display_name=f"#{channel_name.lstrip('#')}",
    )
