"""Phase 2x-B: channel requirements (admin) and setup readiness (member).

The route split mirrors the trust boundary. An admin may declare *what a
channel needs* and see *who is behind on setup*. Only a member may act on
their own connection, and no route here accepts a `connection_id` from
anyone - the OAuth flow in integrations.py is the only way a connection is
ever created, and it always attributes to the caller.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_channel_role
from app.models.channel_required_connection import ChannelRequiredConnection
from app.models.team import ChannelRole, Team
from app.models.user import User
from app.schemas.channel_readiness import (
    ChannelReadinessOut,
    ChannelRequirementCreate,
    ChannelRequirementOut,
    MemberReadinessOut,
    RequirementStatusOut,
)
from app.services.channel_readiness import list_requirements, member_checklist, roster_readiness

router = APIRouter(tags=["channel-readiness"])

_ANY_MEMBER = [ChannelRole.CHANNEL_ADMIN, ChannelRole.CHANNEL_MEMBER]
_ADMIN_ONLY = [ChannelRole.CHANNEL_ADMIN]


def _to_out(requirement: ChannelRequiredConnection) -> ChannelRequirementOut:
    return ChannelRequirementOut(
        id=requirement.id,
        provider=requirement.provider.value,
        is_required=requirement.is_required,
        reason=requirement.reason,
    )


@router.get("/teams/{team_id}/requirements", response_model=list[ChannelRequirementOut])
def list_channel_requirements(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChannelRequirementOut]:
    """Readable by any member: you can't satisfy a requirement you can't see."""
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    return [_to_out(r) for r in list_requirements(session, team_id)]


@router.post("/teams/{team_id}/requirements", response_model=ChannelRequirementOut, status_code=201)
def add_channel_requirement(
    team_id: uuid.UUID,
    payload: ChannelRequirementCreate,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChannelRequirementOut:
    require_channel_role(session, user, team_id, allowed=_ADMIN_ONLY)

    existing = session.query(ChannelRequiredConnection).filter_by(team_id=team_id, provider=payload.provider).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="That integration is already listed for this channel")

    requirement = ChannelRequiredConnection(
        team_id=team_id,
        provider=payload.provider,
        is_required=payload.is_required,
        reason=payload.reason,
        added_by_user_id=user.id,
    )
    session.add(requirement)
    session.commit()
    session.refresh(requirement)
    return _to_out(requirement)


@router.delete("/teams/{team_id}/requirements/{requirement_id}", status_code=204)
def remove_channel_requirement(
    team_id: uuid.UUID,
    requirement_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_channel_role(session, user, team_id, allowed=_ADMIN_ONLY)

    requirement = session.get(ChannelRequiredConnection, requirement_id)
    if requirement is None or requirement.team_id != team_id:
        raise HTTPException(status_code=404, detail="Not found")

    session.delete(requirement)
    session.commit()


@router.get("/teams/{team_id}/readiness", response_model=ChannelReadinessOut)
def my_channel_readiness(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChannelReadinessOut:
    """The caller's own setup checklist. Always about `user`, never about a
    user id supplied by the caller - there is no such parameter."""
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    team = session.get(Team, team_id)

    checklist = member_checklist(session, team_id, team.workspace_id, user.id)
    return ChannelReadinessOut(
        team_id=team_id,
        is_ready=not any(s.blocks for s in checklist),
        blocking_providers=[s.provider.value for s in checklist if s.blocks],
        requirements=[
            RequirementStatusOut(
                provider=s.provider.value,
                is_required=s.is_required,
                reason=s.reason,
                state=s.state.value,
                account_label=s.account_label,
            )
            for s in checklist
        ],
    )


@router.get("/teams/{team_id}/readiness/roster", response_model=list[MemberReadinessOut])
def channel_roster_readiness(
    team_id: uuid.UUID,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[MemberReadinessOut]:
    """Who in this channel still has setup to do. Admin-only, and returns
    states rather than credentials - see services/channel_readiness.py."""
    require_channel_role(session, user, team_id, allowed=_ADMIN_ONLY)
    team = session.get(Team, team_id)
    return [MemberReadinessOut(**row) for row in roster_readiness(session, team_id, team.workspace_id)]
