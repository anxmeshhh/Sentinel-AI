"""AI Command endpoints for a Connection Workspace - see services/orchestrator.py
for the actual tool-calling loop and its safety model. Google only for now
(see PHASES.md's staging note); the route prefix is provider-specific on
purpose rather than generic, so adding another provider later is a new
router, not a branch inside this one.
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.models.user import User
from app.schemas.orchestrator import CommandRequest, CommandResponse, ExecuteActionRequest, ExecuteActionResponse
from app.services.orchestrator import execute_planned_action, run_command, run_command_stream

router = APIRouter(prefix="/connections/google", tags=["connections-ai"])


@router.post("/command", response_model=CommandResponse)
def google_command(
    payload: CommandRequest,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> CommandResponse:
    result = run_command(session, workspace_id, payload.command, user_id=user.id)
    return CommandResponse(status=result.status, reply=result.reply, plan=result.plan, pending_action=result.pending_action, sources=result.sources)


@router.post("/command/stream")
def google_command_stream(
    payload: CommandRequest,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Same loop as /command, but streams each real step as it happens (SSE
    framing) instead of returning only the final answer - what the AI
    Command UI shows as loading text is genuinely what's occurring server
    side at that moment, not a simulated sequence. POST (not GET, despite
    SSE convention) because EventSource can't carry the Authorization header
    this app's auth requires - the frontend reads this with fetch() +
    a stream reader instead of the EventSource API.
    """

    def event_source():
        for event in run_command_stream(session, workspace_id, payload.command, user_id=user.id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.post("/command/execute", response_model=ExecuteActionResponse)
def google_command_execute(
    payload: ExecuteActionRequest,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> ExecuteActionResponse:
    """Only reachable when the user clicks "Confirm & Execute" on a plan the
    /command endpoint returned - the frontend re-submits that exact
    pending_action verbatim. execute_planned_action() re-derives the
    connection from workspace_id itself, so this can't be pointed at
    another workspace's calendar even with a tampered request.
    """
    try:
        result = execute_planned_action(session, workspace_id, payload.name, payload.arguments, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to execute action: {exc}")
    return ExecuteActionResponse(result=result)
