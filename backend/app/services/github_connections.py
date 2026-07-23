"""One GitHub account, many monitored repositories.

## The model, and why it is this shape

A monitored repository is a full `Connection` row of its own. That is the
decision the whole feature rests on: every downstream system - signals,
attention gating, channel sharing, exclusions, investigation, goals - already
keys on `connection_id`, so a repository that is its own connection flows
through all of it with no new plumbing, and gains independent behaviour for
free. One repo can be shared to a channel and another kept private; one can
be excluded, paused, or investigated without touching the rest.

The alternative - an account with a child table of repositories - would have
meant teaching every one of those systems about a new `repository_id`. That
is the redesign this deliberately avoids.

## The cost, and how it is paid

The OAuth token is one account's, but it lives redundantly on each repo row.
So account-level events fan out: reconnecting refreshes the token on every
row, revocation would mark every row, and a different account replacing the
old one wipes every row (its repositories are not the new account's to keep).
`github_login` is what makes that last case detectable - `org` holds a repo's
owner, which is often an organization the user only collaborates in, so it
cannot double as the account's identity.

## Nothing here calls GitHub

The routes verify repositories against the live API before handing them here;
this module only reconciles rows. Keeping the network at the edge is what
lets these decisions be tested without a GitHub in the loop.
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection import Connection, Provider
from app.models.signal import Signal

logger = structlog.get_logger("sentinel.github_connections")


class GitHubAccountError(Exception):
    pass


def account_connections(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> list[Connection]:
    """Every GitHub connection this person holds in this workspace - the
    repositories they monitor, plus a repo-less anchor if they have connected
    but not yet chosen one."""
    return list(session.execute(
        select(Connection).where(
            Connection.workspace_id == workspace_id,
            Connection.user_id == user_id,
            Connection.provider == Provider.GITHUB,
        ).order_by(Connection.repo)
    ).scalars())


def monitored_repositories(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> list[Connection]:
    """Only the rows that actually point at a repository."""
    return [c for c in account_connections(session, workspace_id, user_id) if c.repo]


def connect_github_account(
    session: Session, *, workspace_id: uuid.UUID, user_id: uuid.UUID, login: str, encrypted_token: str
) -> None:
    """Reconcile the account after an OAuth round trip.

    Same account: refresh the token on every repo row and clear any
    revocation - a fresh consent is the evidence the account is alive again.
    Different account: the previous account's repositories are wiped, because
    they are not this token's to read. New account: leave a repo-less anchor,
    the "connected, now choose repositories" state.
    """
    existing = account_connections(session, workspace_id, user_id)
    prior_login = next((c.github_login for c in existing if c.github_login), None)

    if existing and prior_login and prior_login != login:
        logger.info(
            "github_account_switched", old=prior_login, new=login,
            workspace_id=str(workspace_id), repos=len([c for c in existing if c.repo]),
        )
        for connection in existing:
            session.query(Signal).filter(Signal.connection_id == connection.id).delete()
            session.delete(connection)
        existing = []

    if existing:
        for connection in existing:
            connection.encrypted_token = encrypted_token
            connection.github_login = login
            connection.revoked_at = None
        session.commit()
        return

    # No rows for this account - create the anchor. `org` mirrors the login
    # only until a real repository is chosen; from then on it holds the repo
    # owner like every other GitHub row.
    session.add(Connection(
        workspace_id=workspace_id, user_id=user_id, provider=Provider.GITHUB,
        org=login, repo="", github_login=login, encrypted_token=encrypted_token,
    ))
    session.commit()


def add_repository(
    session: Session, *, workspace_id: uuid.UUID, user_id: uuid.UUID, org: str, repo: str
) -> Connection:
    """Start monitoring one more repository under the connected account.

    Fills a repo-less anchor if one exists (the common first-repo case),
    otherwise adds a new row carrying the same token. Idempotent: asking for
    a repository already monitored returns the existing row rather than
    tripping the unique key.
    """
    account = account_connections(session, workspace_id, user_id)
    if not account:
        raise GitHubAccountError("Connect a GitHub account first")

    already = next((c for c in account if c.repo.lower() == repo.lower() and c.org.lower() == org.lower()), None)
    if already is not None:
        return already

    token = account[0].encrypted_token
    login = account[0].github_login

    anchor = next((c for c in account if not c.repo), None)
    if anchor is not None:
        anchor.org = org
        anchor.repo = repo
        anchor.last_synced_at = None
        anchor.last_success_at = None
        anchor.paused_at = None
        session.commit()
        session.refresh(anchor)
        return anchor

    connection = Connection(
        workspace_id=workspace_id, user_id=user_id, provider=Provider.GITHUB,
        org=org, repo=repo, github_login=login, encrypted_token=token,
    )
    session.add(connection)
    session.commit()
    session.refresh(connection)
    return connection


def remove_repository(session: Session, connection: Connection) -> None:
    """Stop monitoring a repository. Its signals cascade with the row.

    If it was the account's only repository, an anchor is left behind so the
    account stays connected and the user can pick a different repository
    without re-authorizing.
    """
    workspace_id, user_id = connection.workspace_id, connection.user_id
    login, token = connection.github_login, connection.encrypted_token

    session.delete(connection)
    session.flush()

    if not monitored_repositories(session, workspace_id, user_id):
        session.add(Connection(
            workspace_id=workspace_id, user_id=user_id, provider=Provider.GITHUB,
            org=login or "", repo="", github_login=login, encrypted_token=token,
        ))
    session.commit()


def set_paused(session: Session, connection: Connection, *, paused: bool) -> Connection:
    """Silence or resume a repository without disconnecting it."""
    connection.paused_at = datetime.now(timezone.utc) if paused else None
    session.commit()
    session.refresh(connection)
    return connection
