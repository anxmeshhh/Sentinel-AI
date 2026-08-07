"""AI Command endpoints for the Microsoft 365 connection - Sentinel's Microsoft
operations advisor. Its own router, like Google's and GitHub's, rather than a
branch inside a shared one.

Read-only by design. The advisor answers from state Sentinel has already
ingested and analysed - it never calls Microsoft Graph during a conversation and
takes no write actions, so there is no confirm-and-execute step here.
"""

import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.models.user import User
from app.schemas.orchestrator import CommandRequest, CommandResponse
from app.services.microsoft_assistant import answer_microsoft_stream

router = APIRouter(prefix="/connections/microsoft", tags=["connections-ai"])


@router.post("/command", response_model=CommandResponse)
def microsoft_command(
    payload: CommandRequest,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> CommandResponse:
    """Non-streaming form: run the advisor and return only the final answer.
    Shares the exact generator the stream uses, so the two can never diverge."""
    reply = ""
    sources: list = []
    status = "done"
    for event in answer_microsoft_stream(session, workspace_id, user.id, payload.command):
        if event.get("type") == "result":
            status = event.get("status", "done")
            reply = event.get("reply") or ""
            sources = event.get("sources") or []
    return CommandResponse(status=status, reply=reply, plan=None, pending_action=None, sources=sources)


@router.post("/command/stream")
def microsoft_command_stream(
    payload: CommandRequest,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Streams each real step (SSE framing) - "Reading your mail and calendar…",
    "Reviewing findings and situations…", then the answer - so the trail the
    panel shows is genuinely what is happening server-side, exactly like the
    Google and GitHub assistants."""

    def event_source():
        for event in answer_microsoft_stream(session, workspace_id, user.id, payload.command):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
