"""One GitHub account, many monitored repositories.

The multi-resource logic this used to hold now lives in provider_account.py,
shared with Slack (the second-instance refactor). This module is GitHub's
vocabulary over it: an account, repositories, a login. The model decision it
rests on is unchanged - a monitored repository is a full Connection row, so it
flows through the whole pipeline via connection_id with no new plumbing.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.connection import Connection, Provider
from app.services import provider_account
from app.services.provider_account import ProviderAccountError, set_paused, set_priority  # re-exported


class GitHubAccountError(ProviderAccountError):
    pass


def account_connections(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> list[Connection]:
    return provider_account.account_connections(session, workspace_id, user_id, Provider.GITHUB)


def monitored_repositories(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> list[Connection]:
    return provider_account.monitored_resources(session, workspace_id, user_id, Provider.GITHUB)


def connect_github_account(
    session: Session, *, workspace_id: uuid.UUID, user_id: uuid.UUID, login: str, encrypted_token: str
) -> None:
    """Reconcile the account after an OAuth round trip. For GitHub the account's
    identity and its display are the same thing - the login."""
    provider_account.connect_account(
        session, workspace_id=workspace_id, user_id=user_id, provider=Provider.GITHUB,
        account_identity=login, encrypted_token=encrypted_token, anchor_org=login,
    )


def add_repository(
    session: Session, *, workspace_id: uuid.UUID, user_id: uuid.UUID, org: str, repo: str
) -> Connection:
    try:
        return provider_account.add_resource(
            session, workspace_id=workspace_id, user_id=user_id, provider=Provider.GITHUB, org=org, repo=repo
        )
    except ProviderAccountError:
        raise GitHubAccountError("Connect a GitHub account first")


def remove_repository(session: Session, connection: Connection) -> None:
    provider_account.remove_resource(session, connection)


__all__ = [
    "GitHubAccountError",
    "account_connections",
    "monitored_repositories",
    "connect_github_account",
    "add_repository",
    "remove_repository",
    "set_paused",
    "set_priority",
]
