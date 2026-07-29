"""One account, many monitored resources - for any provider.

This is the GitHub multi-repository model, lifted into one place now that Slack
is its second instance (the second-instance refactor the pre-Slack design
review named). A monitored resource - a GitHub repository, a Slack channel - is
a full Connection row of its own, so it flows through the entire pipeline
(signals, attention, sharing, investigation, goals) via connection_id with no
new plumbing, and can be paused, classified, shared or removed on its own.

The account's OAuth grant is one token shared across its resource rows. So
account-level events fan out: reconnecting refreshes the token everywhere, and
a *different* account replacing the old one wipes the old rows (their resources
are not the new grant's to read). `github_login` - the misnamed-but-generic
account identity field - is what makes that last case detectable.

What differs per provider stays out of here: how the OAuth grant is obtained,
what a resource is called, how it is discovered. Those live in the provider's
own module (github_connections, slack_connections), which call these functions.
"""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection import Connection, Provider, ResourcePriority
from app.models.signal import Signal

logger = structlog.get_logger("sentinel.provider_account")


class ProviderAccountError(Exception):
    pass


def account_connections(
    session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID, provider: Provider
) -> list[Connection]:
    """Every connection this person holds for this provider in this workspace -
    the monitored resources, plus a resource-less anchor if they have connected
    but not yet chosen one."""
    return list(session.execute(
        select(Connection).where(
            Connection.workspace_id == workspace_id,
            Connection.user_id == user_id,
            Connection.provider == provider,
        ).order_by(Connection.repo)
    ).scalars())


def monitored_resources(
    session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID, provider: Provider
) -> list[Connection]:
    """Only the rows that actually point at a resource (repo/channel chosen)."""
    return [c for c in account_connections(session, workspace_id, user_id, provider) if c.repo]


def connect_account(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    provider: Provider,
    account_identity: str,
    encrypted_token: str,
    anchor_org: str | None = None,
) -> Connection:
    """Reconcile an account after an OAuth round trip.

    Same account reconnected: refresh the token on every resource row and clear
    revocation. Different account: the previous account's rows are wiped.
    New account: leave a resource-less anchor - the "connected, choose a
    resource" state. `anchor_org` is the account's display name (a GitHub login,
    a Slack workspace name); it defaults to the identity for providers where
    they coincide.
    """
    display_org = anchor_org or account_identity
    existing = account_connections(session, workspace_id, user_id, provider)
    prior_identity = next((c.github_login for c in existing if c.github_login), None)

    if existing and prior_identity and prior_identity != account_identity:
        logger.info(
            "provider_account_switched", provider=provider.value,
            old=prior_identity, new=account_identity, workspace_id=str(workspace_id),
            resources=len([c for c in existing if c.repo]),
        )
        for connection in existing:
            session.query(Signal).filter(Signal.connection_id == connection.id).delete()
            session.delete(connection)
        existing = []

    if existing:
        for connection in existing:
            connection.encrypted_token = encrypted_token
            connection.github_login = account_identity
            connection.revoked_at = None
            # Only the anchor's org is refreshed - a resource row's org is the
            # resource's own owner (a GitHub repo's owner) and must not be
            # overwritten with the account display.
            if not connection.repo:
                connection.org = display_org
        session.commit()
        return next((c for c in existing if not c.repo), existing[0])

    anchor = Connection(
        workspace_id=workspace_id, user_id=user_id, provider=provider,
        org=display_org, repo="", github_login=account_identity, encrypted_token=encrypted_token,
    )
    session.add(anchor)
    session.commit()
    session.refresh(anchor)
    return anchor


def add_resource(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    provider: Provider,
    org: str,
    repo: str,
    display_name: str | None = None,
) -> Connection:
    """Start monitoring one more resource under the connected account.

    Fills a resource-less anchor if one exists (the common first-resource case),
    otherwise adds a new row carrying the same token. Idempotent: a resource
    already monitored is returned rather than tripping the unique key.
    """
    account = account_connections(session, workspace_id, user_id, provider)
    if not account:
        raise ProviderAccountError("Connect an account first")

    already = next(
        (c for c in account if c.repo.lower() == repo.lower() and c.org.lower() == org.lower()), None
    )
    if already is not None:
        return already

    token = account[0].encrypted_token
    identity = account[0].github_login

    anchor = next((c for c in account if not c.repo), None)
    if anchor is not None:
        anchor.org = org
        anchor.repo = repo
        anchor.display_name = display_name
        anchor.last_synced_at = None
        anchor.last_success_at = None
        anchor.paused_at = None
        session.commit()
        session.refresh(anchor)
        return anchor

    connection = Connection(
        workspace_id=workspace_id, user_id=user_id, provider=provider,
        org=org, repo=repo, display_name=display_name, github_login=identity, encrypted_token=token,
    )
    session.add(connection)
    session.commit()
    session.refresh(connection)
    return connection


def remove_resource(session: Session, connection: Connection) -> None:
    """Stop monitoring a resource. Its signals cascade with the row.

    If it was the account's only resource, an anchor is left behind so the
    account stays connected and another resource can be chosen without
    re-authorizing.
    """
    workspace_id, user_id, provider = connection.workspace_id, connection.user_id, connection.provider
    identity, token = connection.github_login, connection.encrypted_token

    session.delete(connection)
    session.flush()

    if not monitored_resources(session, workspace_id, user_id, provider):
        session.add(Connection(
            workspace_id=workspace_id, user_id=user_id, provider=provider,
            org=identity or "", repo="", github_login=identity, encrypted_token=token,
        ))
    session.commit()


def set_paused(session: Session, connection: Connection, *, paused: bool) -> Connection:
    """Silence or resume a resource without disconnecting it."""
    from datetime import datetime, timezone

    connection.paused_at = datetime.now(timezone.utc) if paused else None
    session.commit()
    session.refresh(connection)
    return connection


def set_priority(session: Session, connection: Connection, priority: ResourcePriority) -> Connection:
    """Classify how much this resource matters.

    The classification is the context that decides whether activity-based
    attention (a critical resource gone silent) fires for it - so changing it
    changes what Sentinel surfaces, not just a label.
    """
    connection.priority = priority
    session.commit()
    session.refresh(connection)
    return connection
