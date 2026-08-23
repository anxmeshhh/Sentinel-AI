"""Meeting History for the Google Meet Workspace - see services/meet_query.py
for what this is (and isn't) built from.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.models.signal import Signal
from app.models.user import User
from app.schemas.meet import MeetingOut
from app.services.investigation import personal_scope
from app.services.meet_query import MEETING_RANGES, list_meetings, meeting_status

router = APIRouter(prefix="/meet", tags=["meet"])


@router.get("/history", response_model=list[MeetingOut])
def get_meeting_history(
    range: str = "upcoming",
    search: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[MeetingOut]:
    """The caller's own meeting history.

    Scoped to their connections, not the workspace: a meeting carries its
    title, attendees and a joinable link, so a workspace-wide list handed one
    member another's calendar."""
    if range not in MEETING_RANGES:
        raise HTTPException(status_code=400, detail=f"Unknown range. Use one of: {sorted(MEETING_RANGES)}")
    scope = personal_scope(session, workspace_id, user.id)
    signals = list_meetings(
        session, workspace_id, meeting_range=range, search=search, limit=min(limit, 100),
        connection_ids=scope.connection_ids,
    )
    return [_to_item(s) for s in signals]


def _to_item(s: Signal) -> MeetingOut:
    return MeetingOut(
        id=s.id,
        title=s.payload.get("title", "(no title)"),
        start=s.payload.get("start"),
        end=s.payload.get("end"),
        occurred_at=s.occurred_at,
        attendee_count=s.payload.get("attendee_count", 0),
        attendee_emails=s.payload.get("attendee_emails", []),
        status=meeting_status(s),
        calendar_url=s.payload.get("url"),
        meet_url=s.payload.get("meet_url"),
    )
