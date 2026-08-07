"""provision_grant - the one place a workspace-provider's child connections are
created or updated, generalized from the old Google-specific loop (N=2).

One OAuth grant delegates one individual's access, so every child connection is
keyed on (workspace, user, provider) and shares the grant's token and account
identity. Re-connecting a *different* account as the same person replaces their
own connections and purges the signals that describe an account they can no
longer read - scoped to that user, never touching a teammate's. Google and
Microsoft both flow through here; nothing about it is provider-specific beyond
the grant's declared service list.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection import Connection
from app.models.email_summary import EmailSummary
from app.models.signal import Signal
from app.providers.workspace_grants import MAIL_PROVIDERS, WorkspaceGrantSpec
from app.services import provider_account

logger = structlog.get_logger("sentinel.grants")


def provision_grant(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    grant: WorkspaceGrantSpec,
    account_identity: str,
    encrypted_token: str,
) -> None:
    """Create or refresh every child connection of one grant for one user."""
    # Anchor providers (Teams channels, later Planner plans) delegate to
    # provider_account.connect_account - the same path GitHub and Slack use.
    # That matters on reconnect: an anchor provider has MANY rows (the anchor
    # plus every chosen resource) all sharing this one grant's token, and
    # connect_account already refreshes every row, clears revocation, and wipes
    # the old account's resources if a different account signs in. Reimplementing
    # that here would be a second, weaker copy of logic that already exists.
    for provider in grant.anchors:
        provider_account.connect_account(
            session, workspace_id=workspace_id, user_id=user_id, provider=provider,
            account_identity=account_identity, encrypted_token=encrypted_token,
        )

    for provider, label in grant.services:
        existing = session.execute(
            select(Connection).where(
                Connection.workspace_id == workspace_id,
                Connection.user_id == user_id,
                Connection.provider == provider,
            )
        ).scalars().first()

        if existing is not None:
            if existing.org != account_identity:
                # A different account for the same person: the previously synced
                # signals describe a mailbox/calendar this account can no longer
                # read, so they are purged. Scoped to this connection only.
                logger.info(
                    "grant_account_replaced",
                    grant=grant.key, provider=provider.value,
                    old=existing.org, new=account_identity,
                    workspace_id=str(workspace_id), user_id=str(user_id),
                )
                session.query(Signal).filter(Signal.connection_id == existing.id).delete()
                if provider in MAIL_PROVIDERS:
                    session.query(EmailSummary).filter(EmailSummary.workspace_id == workspace_id).delete()
                existing.org = account_identity
                existing.last_synced_at = None
            existing.encrypted_token = encrypted_token
            # A fresh consent is exactly the evidence the connection is alive
            # again - otherwise it stays flagged expired forever after a revoke.
            existing.revoked_at = None
        else:
            session.add(
                Connection(
                    workspace_id=workspace_id, user_id=user_id, provider=provider,
                    org=account_identity, repo=label, encrypted_token=encrypted_token,
                )
            )
    session.commit()
