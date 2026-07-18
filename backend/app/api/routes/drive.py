"""Structured, deterministic Drive search for the Drive workspace page's own
browse UI - separate from (but sharing the same query builder and client as)
the AI Command orchestrator's search_drive tool. No LLM involved here.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_workspace_id
from app.integrations.google_auth import get_valid_access_token
from app.integrations.google_drive_client import GoogleDriveClient
from app.models.connection import Provider
from app.repositories.connections import ConnectionRepository
from app.schemas.drive import DriveFileOut
from app.services.drive_query import build_drive_query

router = APIRouter(prefix="/drive", tags=["drive"])


@router.get("/search", response_model=list[DriveFileOut])
def search_drive(
    query: str | None = None,
    mime_type: str | None = None,
    modified_after: str | None = None,
    shared_with_me: bool = False,
    limit: int = 20,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list[DriveFileOut]:
    connection = ConnectionRepository(session, workspace_id).get_by_provider(Provider.GOOGLE_DRIVE)
    if connection is None:
        raise HTTPException(status_code=404, detail="Google Drive is not connected")

    q = build_drive_query(keywords=query, mime_type=mime_type, modified_after=modified_after, shared_with_me=shared_with_me)
    access_token = get_valid_access_token(session, connection)
    with GoogleDriveClient(access_token) as client:
        files = client.search(q, max_results=min(limit, 50))
    return [DriveFileOut(**f) for f in files]
