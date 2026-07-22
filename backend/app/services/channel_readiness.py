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

## State is not the same question as blocking (Phase 3)

`state` answers "has *this member* connected this service themselves?".
Whether the member is *blocked* is a second question, and since Phase 3 the
answer is no whenever an admin has already shared that provider with the
channel (`provided_by`). The two are kept apart deliberately: a member whose
channel is covered by an admin's Gmail is `not_connected` *and* unblocked,
and reporting them as "connected" would be a lie about their own account.

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
from app.services.channel_authorization import authorized_connections

# Same ordering the resolver uses to attribute a connection to a tier.
_TIER_RANK = {"workspace": 0, "class": 1, "group": 2, "channel": 3}


class ReadinessState(str, enum.Enum):
    NOT_CONNECTED = "not_connected"
    SYNCING = "syncing"
    READY = "ready"
    EXPIRED = "expired"


class RequirementStatus:
    """One row of a member's setup checklist."""

    def __init__(
        self,
        provider: Provider,
        *,
        is_required: bool,
        reason: str | None,
        state: ReadinessState,
        account_label: str | None,
        provided_by: str | None = None,
    ):
        self.provider = provider
        self.is_required = is_required
        self.reason = reason
        self.state = state
        self.account_label = account_label
        # Which tier already supplies this provider as shared context, if any:
        # "workspace" | "class" | "group" | "channel". None means nobody has
        # shared it and the member's own account is the only way to satisfy it.
        self.provided_by = provided_by

    @property
    def blocks(self) -> bool:
        # Phase 3: an admin who already shared this service has satisfied the
        # requirement for the whole channel. Making the member connect their
        # own account on top of it buys the channel nothing - shared context
        # is resolved from shared connections only (channel_authorization),
        # never from a member's personal one - so it was pure friction, and
        # friction that pushed private mailboxes into a team workspace for no
        # gain. The member may still connect privately; it just isn't a gate.
        if self.provided_by is not None:
            return False
        return self.is_required and self.state != ReadinessState.READY


# Providers whose data is fetched live on every request rather than ingested
# into Signals (see integrations.INGESTABLE_PROVIDERS). They have no first
# sync to wait for, so `last_synced_at` stays NULL forever - reading it as
# "still syncing" left Google Drive permanently stuck on Syncing and
# permanently blocking channel setup, since 3/3 could never be reached.
_LIVE_QUERY_PROVIDERS = {Provider.GOOGLE_DRIVE}


def _state_for(connection: Connection | None) -> ReadinessState:
    if connection is None:
        return ReadinessState.NOT_CONNECTED
    if connection.revoked_at is not None:
        return ReadinessState.EXPIRED
    if connection.provider in _LIVE_QUERY_PROVIDERS:
        # Nothing to ingest: authorized means usable, immediately.
        return ReadinessState.READY
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


def provided_providers(session: Session, team_id: uuid.UUID) -> dict[Provider, str]:
    """provider -> the tier that already supplies it as shared context.

    Reads through the Phase 2 resolver, so a requirement counts as satisfied
    by exactly the same authorization the channel's Feed and Briefing use.
    An excluded connection is absent from the resolver's result, so excluding
    it here correctly puts the requirement back on the member.
    """
    provided: dict[Provider, str] = {}
    for auth in authorized_connections(session, team_id).values():
        current = provided.get(auth.connection.provider)
        # Most specific tier wins the label, matching how the resolver itself
        # attributes a connection authorized at more than one level.
        if current is None or _TIER_RANK[auth.source] > _TIER_RANK[current]:
            provided[auth.connection.provider] = auth.source
    return provided


def member_checklist(session: Session, team_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID) -> list[RequirementStatus]:
    """This member's own setup checklist for this channel.

    A member's *own* connection is looked up by `(workspace, this user,
    provider)` only - there is no fallback to a workspace-wide connection, so
    `state` and `account_label` are never reported on the strength of a
    teammate's account.

    Separately, `provided_by` records whether an admin already shared that
    provider with this channel. That is what makes a requirement non-blocking
    (see RequirementStatus.blocks); it never changes `state`, which continues
    to describe only this member's own connection - conflating the two would
    tell a member they had connected something they hadn't.
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
    provided = provided_providers(session, team_id)

    return [
        RequirementStatus(
            r.provider,
            is_required=r.is_required,
            reason=r.reason,
            state=_state_for(owned.get(r.provider)),
            account_label=owned[r.provider].full_name if r.provider in owned else None,
            provided_by=provided.get(r.provider),
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
                        "provided_by": s.provided_by,
                    }
                    for s in checklist
                ],
            }
        )
    return roster


def channel_workspace_id(session: Session, team_id: uuid.UUID) -> uuid.UUID:
    team = session.get(Team, team_id)
    return team.workspace_id
