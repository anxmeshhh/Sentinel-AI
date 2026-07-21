"""Phase 2x-B: is *this member* set up for *this channel*?

An admin declares which providers a channel needs
(`ChannelRequiredConnection`). Each member satisfies those requirements with
their own account (`Connection`, owned per-user since Phase A). This module
is the join between the two, and the single place that decides whether a
member is blocked.

## The state machine

    not_connected -> syncing -> ready
                         \\-> expired -> (reconnect) -> syncing

Every state is derived from a fact already in the database:

| State           | Evidence                                            |
|-----------------|-----------------------------------------------------|
| `not_connected` | no Connection row for (workspace, member, provider) |
| `expired`       | `revoked_at` is set - a token refresh actually failed |
| `syncing`       | connected, `last_synced_at` is NULL                 |
| `ready`         | connected and synced at least once                  |

**There is deliberately no `connecting` state.** The OAuth round-trip happens
on Google's servers; between the redirect out and the callback back, this
database holds no row and no evidence. A `connecting` state would be a
frontend spinner promoted to a server-side fact, and it would get stuck the
moment a user abandoned the consent screen. The frontend can show whatever
transient affordance it likes; the API only reports what it can prove.

## What this module must never do

Readiness is computed *about* a member, but it never exposes a member's
credentials. The output carries a provider, a state, and the account label
the member themselves connected - never a token, never a connection id that
would let an admin address someone else's row. See `MemberReadiness`.
"""

import enum
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.channel_required_connection import ChannelRequiredConnection
from app.models.connection import Connection, Provider
from app.models.team import Team, TeamMembership
from app.models.user import User


class ReadinessState(str, enum.Enum):
    NOT_CONNECTED = "not_connected"
    SYNCING = "syncing"
    READY = "ready"
    EXPIRED = "expired"


class RequirementStatus:
    """One row of a member's setup checklist."""

    def __init__(self, provider: Provider, *, is_required: bool, reason: str | None, state: ReadinessState, account_label: str | None):
        self.provider = provider
        self.is_required = is_required
        self.reason = reason
        self.state = state
        self.account_label = account_label

    @property
    def blocks(self) -> bool:
        return self.is_required and self.state != ReadinessState.READY


def _state_for(connection: Connection | None) -> ReadinessState:
    if connection is None:
        return ReadinessState.NOT_CONNECTED
    if connection.revoked_at is not None:
        return ReadinessState.EXPIRED
    if connection.last_synced_at is None:
        return ReadinessState.SYNCING
    return ReadinessState.READY


def list_requirements(session: Session, team_id: uuid.UUID) -> list[ChannelRequiredConnection]:
    return list(
        session.execute(
            select(ChannelRequiredConnection)
            .where(ChannelRequiredConnection.team_id == team_id)
            .order_by(ChannelRequiredConnection.is_required.desc(), ChannelRequiredConnection.created_at)
        ).scalars()
    )


def member_checklist(session: Session, team_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID) -> list[RequirementStatus]:
    """This member's own setup checklist for this channel.

    Looks up connections by `(workspace, this user, provider)` only. There is
    no fallback to a workspace-wide connection, so a member is never reported
    ready on the strength of a teammate's account.
    """
    requirements = list_requirements(session, team_id)
    if not requirements:
        return []

    owned = {
        c.provider: c
        for c in session.execute(
            select(Connection).where(Connection.workspace_id == workspace_id, Connection.user_id == user_id)
        ).scalars()
    }

    return [
        RequirementStatus(
            r.provider,
            is_required=r.is_required,
            reason=r.reason,
            state=_state_for(owned.get(r.provider)),
            account_label=owned[r.provider].full_name if r.provider in owned else None,
        )
        for r in requirements
    ]


def blocking_providers(session: Session, team_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID) -> list[Provider]:
    """The required providers this member has not satisfied.

    Callers use this to explain an empty result instead of silently
    returning one - "you haven't connected Gmail yet" is a fixable answer,
    "no items" is not.
    """
    return [status.provider for status in member_checklist(session, team_id, workspace_id, user_id) if status.blocks]


def roster_readiness(session: Session, team_id: uuid.UUID, workspace_id: uuid.UUID) -> list[dict]:
    """Per-member readiness for a channel admin.

    An admin needs to know *who* still has setup to do - that is the whole
    operational point of declaring requirements. What they must not get is
    any handle on a member's credentials, so each entry carries only the
    member's identity plus a provider/state pair. No tokens, no connection
    ids, and the account label is the address the member connected
    themselves (already visible to them, and the only way "connected the
    wrong account" is diagnosable).
    """
    members = session.execute(
        select(User, TeamMembership)
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .where(TeamMembership.team_id == team_id)
    ).all()

    roster = []
    for user, membership in members:
        checklist = member_checklist(session, team_id, workspace_id, user.id)
        roster.append(
            {
                "user_id": user.id,
                "name": user.name,
                "email": user.email,
                "role": membership.role.value,
                "is_ready": not any(s.blocks for s in checklist),
                "requirements": [
                    {
                        "provider": s.provider.value,
                        "is_required": s.is_required,
                        "state": s.state.value,
                        "account_label": s.account_label,
                    }
                    for s in checklist
                ],
            }
        )
    return roster


def channel_workspace_id(session: Session, team_id: uuid.UUID) -> uuid.UUID:
    team = session.get(Team, team_id)
    return team.workspace_id
