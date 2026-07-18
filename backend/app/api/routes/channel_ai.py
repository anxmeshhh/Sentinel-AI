"""Phase 2m: Channel AI - the same orchestrator tool-calling loop as
/connections/google/command/*, scoped to one Channel's authorized
Connections/resources instead of the whole Workspace. See
services/orchestrator.py's run_command_stream docstring for what team_id
actually changes.
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_channel_role
from app.models.channel_ai_history import ChannelAIHistoryEntry
from app.models.team import ChannelRole, Team
from app.models.user import User
from app.schemas.channel_ai import ChannelAIHistoryOut
from app.schemas.orchestrator import CommandRequest, CommandResponse, ExecuteActionRequest, ExecuteActionResponse
from app.services.orchestrator import execute_planned_action, run_command, run_command_stream

router = APIRouter(tags=["channel-ai"])

_ANY_MEMBER = [ChannelRole.CHANNEL_ADMIN, ChannelRole.CHANNEL_MEMBER]


def _get_team_or_404(session: Session, team_id: uuid.UUID) -> Team:
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.post("/teams/{team_id}/ai/command", response_model=CommandResponse)
def channel_ai_command(
    team_id: uuid.UUID,
    payload: CommandRequest,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommandResponse:
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    team = _get_team_or_404(session, team_id)
    result = run_command(session, team.workspace_id, payload.command, team_id=team_id, user_id=user.id)
    return CommandResponse(status=result.status, reply=result.reply, plan=result.plan, pending_action=result.pending_action)


@router.post("/teams/{team_id}/ai/command/stream")
def channel_ai_command_stream(
    team_id: uuid.UUID,
    payload: CommandRequest,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    team = _get_team_or_404(session, team_id)

    def event_source():
        for event in run_command_stream(session, team.workspace_id, payload.command, team_id=team_id, user_id=user.id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.post("/teams/{team_id}/ai/command/execute", response_model=ExecuteActionResponse)
def channel_ai_command_execute(
    team_id: uuid.UUID,
    payload: ExecuteActionRequest,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExecuteActionResponse:
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)
    team = _get_team_or_404(session, team_id)
    try:
        result = execute_planned_action(session, team.workspace_id, payload.name, payload.arguments)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to execute action: {exc}")
    return ExecuteActionResponse(result=result)


@router.get("/teams/{team_id}/ai/history", response_model=list[ChannelAIHistoryOut])
def channel_ai_history(
    team_id: uuid.UUID,
    limit: int = 30,
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChannelAIHistoryOut]:
    require_channel_role(session, user, team_id, allowed=_ANY_MEMBER)

    rows = session.execute(
        select(ChannelAIHistoryEntry, User.name)
        .join(User, User.id == ChannelAIHistoryEntry.user_id)
        .where(ChannelAIHistoryEntry.team_id == team_id)
        .order_by(ChannelAIHistoryEntry.created_at.desc())
        .limit(min(limit, 100))
    ).all()
    return [
        ChannelAIHistoryOut(id=entry.id, user_id=entry.user_id, user_name=name, command=entry.command, reply=entry.reply, created_at=entry.created_at)
        for entry, name in rows
    ]
