"""One Slack workspace, connected.

Phase 0 stores exactly one thing per user+workspace: the Slack workspace anchor
- a Connection holding the bot token, with no channel chosen yet (`repo == ""`),
the direct analogue of the GitHub account anchor. Channels become their own
Connections under this grant in Phase 1, which is also when the account-with-
many-resources logic shared with GitHub gets lifted into one helper (it is
deliberately duplicated in miniature here until that second-instance refactor).

`github_login` carries the Slack team id here. The column name is a GitHub-era
wart - it is really "the account's stable identity", the thing that tells a
reconnect of a *different* workspace apart from a token refresh of the same one.
It is renamed to something provider-neutral in the Phase 1 generalization; for
now the field does its job under the wrong name, and this comment is the note.
"""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.connection import Connection, Provider
from app.models.signal import Signal

logger = structlog.get_logger("sentinel.slack_connections")


def slack_workspace(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Connection | None:
    """This user's Slack workspace connection in this Sentinel workspace, if any."""
    return session.execute(
        select(Connection).where(
            Connection.workspace_id == workspace_id,
            Connection.user_id == user_id,
            Connection.provider == Provider.SLACK,
        ).order_by(Connection.repo)
    ).scalars().first()


def connect_slack_workspace(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    team_id: str,
    team_name: str,
    encrypted_token: str,
) -> Connection:
    """Reconcile the Slack account after an OAuth round trip.

    Same workspace reconnected: refresh the bot token and clear any revocation.
    A *different* workspace: the previous one's rows are wiped, because its
    channels are not this token's to read. New: create the anchor - the
    "connected, no channels chosen yet" state Phase 1 fills in.
    """
    existing = session.execute(
        select(Connection).where(
            Connection.workspace_id == workspace_id,
            Connection.user_id == user_id,
            Connection.provider == Provider.SLACK,
        )
    ).scalars().all()
    prior_team = next((c.github_login for c in existing if c.github_login), None)

    if existing and prior_team and prior_team != team_id:
        logger.info(
            "slack_workspace_switched", old=prior_team, new=team_id,
            workspace_id=str(workspace_id), rows=len(existing),
        )
        for connection in existing:
            session.query(Signal).filter(Signal.connection_id == connection.id).delete()
            session.delete(connection)
        existing = []

    if existing:
        for connection in existing:
            connection.encrypted_token = encrypted_token
            connection.github_login = team_id
            connection.org = team_name
            connection.revoked_at = None
        session.commit()
        return existing[0]

    anchor = Connection(
        workspace_id=workspace_id,
        user_id=user_id,
        provider=Provider.SLACK,
        org=team_name,     # display name of the workspace, until a channel is chosen
        repo="",           # anchor: connected, no channel selected yet
        github_login=team_id,  # the account's stable identity (see module docstring)
        encrypted_token=encrypted_token,
    )
    session.add(anchor)
    session.commit()
    session.refresh(anchor)
    return anchor
