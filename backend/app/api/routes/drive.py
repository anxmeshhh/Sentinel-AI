"""Structured, deterministic Drive search for the Drive workspace page's own
browse UI - separate from (but sharing the same query builder and client as)
the AI Command orchestrator's search_drive tool. No LLM involved here.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_workspace_id
from app.integrations.google_auth import get_valid_access_token
from app.integrations.google_drive_client import GoogleDriveClient
from app.models.connection import Provider
from app.models.user import User
from app.repositories.connections import ConnectionRepository
from app.schemas.drive import DriveAnalyticsOut, DriveFileOut
from app.services.drive_query import build_drive_query, get_drive_analytics

router = APIRouter(prefix="/drive", tags=["drive"])


@router.get("/analytics", response_model=DriveAnalyticsOut)
def drive_analytics(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> DriveAnalyticsOut:
    result = get_drive_analytics(session, workspace_id, user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="Google Drive is not connected")
    return DriveAnalyticsOut(
        recent_files=[DriveFileOut(**f) for f in result["recent_files"]],
        shared_files=[DriveFileOut(**f) for f in result["shared_files"]],
        type_counts=result["type_counts"],
        large_files=[DriveFileOut(**f) for f in result["large_files"]],
        storage_used_bytes=result["storage_used_bytes"],
        storage_limit_bytes=result["storage_limit_bytes"],
    )


@router.get("/search", response_model=list[DriveFileOut])
def search_drive(
    query: str | None = None,
    mime_type: str | None = None,
    modified_after: str | None = None,
    shared_with_me: bool = False,
    limit: int = 20,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
    user: User = Depends(get_current_user),
) -> list[DriveFileOut]:
    connection = ConnectionRepository(session, workspace_id).get_for_user(user.id, Provider.GOOGLE_DRIVE)
    if connection is None:
        raise HTTPException(status_code=404, detail="Google Drive is not connected")

    q = build_drive_query(keywords=query, mime_type=mime_type, modified_after=modified_after, shared_with_me=shared_with_me)
    access_token = get_valid_access_token(session, connection)
    with GoogleDriveClient(access_token) as client:
        files = client.search(q, max_results=min(limit, 50))
    return [DriveFileOut(**f) for f in files]
