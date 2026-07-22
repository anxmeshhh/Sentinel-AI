"""Proactive Intelligence: what Sentinel noticed without being asked.

Two entry points, one per intelligence layer, for the same reason
Investigate This has two: the scope decides what may be read, so it is
derived server-side and never accepted as a parameter.

    GET  /proactive                    your own situations (private)
    GET  /teams/{team_id}/proactive    this channel's situations (shared)

GET reads what is already known and costs nothing. `?refresh=true` re-runs
detection, which is deterministic, and synthesizes prose only for situations
whose evidence actually changed.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id, require_channel_role
from app.models.situation import Situation
from app.models.team import ChannelRole, Team
from app.models.user import User
from app.schemas.investigation import InvestigationOut
from app.schemas.situation import SituationOut
from app.services.investigation import (
    NotAuthorized,
    Scope,
    channel_scope,
    investigate_situation,
    personal_scope,
)
from app.services.proactive import investigatable_item_id, list_situations, refresh_situations

router = APIRouter(tags=["proactive"])

_ANY_MEMBER = [ChannelRole.CHANNEL_ADMIN, ChannelRole.CHANNEL_MEMBER]


def _serialize(session: Session, situations) -> list[SituationOut]:
    """Attach the investigation link, which is a lookup rather than a column -
    it depends on whether one of the evidence signals also produced an
    attention item."""
    out = []
    for situation in situations:
        payload = SituationOut.model_validate(situation, from_attributes=True)
        payload.investigatable_item_id = investigatable_item_id(session, situation)
        out.append(payload)
    return out



@router.get("/proactive", response_model=list[SituationOut])
def my_situations(
    refresh: bool = False,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[SituationOut]:
    """Situations detected from the caller's own connections.

    Private by construction: the scope is the caller's own accounts, so
    nothing another member connected can contribute to it.
    """
    scope = personal_scope(session, workspace_id, user.id)
    situations = refresh_situations(session, workspace_id, scope) if refresh else list_situations(session, scope)
    return _serialize(session, situations)


@router.get("/teams/{team_id}/proactive", response_model=list[SituationOut])
def channel_situations(
    team_id: uuid.UUID,
    refresh: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SituationOut]:
    """Situations detected from what this channel is authorized to see.

    The scope comes from the channel, not the caller, so a member's private
    mail cannot become shared team intelligence even though a member is the
    one loading the page.
    """
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    team = session.get(Team, team_id)
    scope = channel_scope(session, team_id)
    situations = (
        refresh_situations(session, team.workspace_id, scope) if refresh else list_situations(session, scope)
    )
    return _serialize(session, situations)


# --- situation -> Investigate This ----------------------------------------


def _situation_or_404(session: Session, situation_id: uuid.UUID, workspace_id: uuid.UUID) -> Situation:
    situation = session.get(Situation, situation_id)
    if situation is None or situation.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Not found")
    return situation


@router.post("/proactive/{situation_id}/investigate", response_model=InvestigationOut)
def investigate_my_situation(
    situation_id: uuid.UUID,
    refresh: bool = False,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> InvestigationOut:
    """Investigate one of your own situations, in your own scope."""
    situation = _situation_or_404(session, situation_id, workspace_id)
    try:
        return investigate_situation(
            session,
            situation=situation,
            scope=personal_scope(session, workspace_id, user.id),
            refresh=refresh,
        )
    except NotAuthorized as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/teams/{team_id}/proactive/{situation_id}/investigate", response_model=InvestigationOut)
def investigate_channel_situation(
    team_id: uuid.UUID,
    situation_id: uuid.UUID,
    refresh: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InvestigationOut:
    """Investigate a channel situation, in that channel's scope.

    The service refuses any situation whose own scope_key is not this
    channel's, so a personal situation cannot be re-investigated as shared
    team context even by someone who can see both.
    """
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    team = session.get(Team, team_id)
    situation = _situation_or_404(session, situation_id, team.workspace_id)
    try:
        return investigate_situation(
            session, situation=situation, scope=channel_scope(session, team_id), refresh=refresh
        )
    except NotAuthorized as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
