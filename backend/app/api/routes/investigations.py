"""Investigate This.

Two entry points, one per authorization scope, because the scope is not a
parameter a caller should get to choose freely - it decides what the
investigation may read. A member could otherwise ask for a "channel"
investigation of their own private mail, or vice versa.

    POST /attention/{item_id}/investigate                 the caller's own context
    POST /teams/{team_id}/attention/{item_id}/investigate  a channel's context

Both re-derive the scope server-side and hand it to the service, which
refuses any item whose source is not in it.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id, require_channel_role
from app.models.attention_item import AttentionItem
from app.models.team import ChannelRole, Team
from app.models.user import User
from app.schemas.investigation import InvestigationOut
from app.services.investigation import (
    NotAuthorized,
    channel_scope,
    investigate,
    personal_scope,
)

router = APIRouter(tags=["investigations"])

_ANY_MEMBER = [ChannelRole.CHANNEL_ADMIN, ChannelRole.CHANNEL_MEMBER]


def _item_or_404(session: Session, item_id: uuid.UUID, workspace_id: uuid.UUID) -> AttentionItem:
    item = session.get(AttentionItem, item_id)
    if item is None or item.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Not found")
    return item


@router.post("/attention/{item_id}/investigate", response_model=InvestigationOut)
def investigate_personally(
    item_id: uuid.UUID,
    refresh: bool = False,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> InvestigationOut:
    """Investigate within the caller's own connections.

    Nothing another member connected is readable here, and nothing shared
    with a channel is either - this scope is exactly the caller's own
    accounts, which is what makes it safe to run over private mail.
    """
    item = _item_or_404(session, item_id, workspace_id)
    try:
        return investigate(
            session, item=item, scope=personal_scope(session, workspace_id, user.id), refresh=refresh
        )
    except NotAuthorized as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/teams/{team_id}/attention/{item_id}/investigate", response_model=InvestigationOut)
def investigate_in_channel(
    team_id: uuid.UUID,
    item_id: uuid.UUID,
    refresh: bool = False,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> InvestigationOut:
    """Investigate within a channel's authorized connections.

    Membership is checked first, then the scope is resolved from the channel
    rather than from the caller - so an investigation run here draws on
    exactly what the channel may see, and never on the investigator's own
    private accounts even though they are the one clicking.
    """
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    team = session.get(Team, team_id)
    item = _item_or_404(session, item_id, team.workspace_id)
    try:
        return investigate(session, item=item, scope=channel_scope(session, team_id), refresh=refresh)
    except NotAuthorized as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
