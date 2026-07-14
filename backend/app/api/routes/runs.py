import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_workspace_id
from app.models.agent_run import TriggeredBy
from app.repositories.connections import ConnectionRepository
from app.schemas.run import RunTrigger
from app.workers.tasks import ingest_connection

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", status_code=202)
def trigger_run(
    payload: RunTrigger,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> dict:
    """The 'Re-run now' action - re-ingests fresh data, then re-runs the agent graph."""
    connection = ConnectionRepository(session, workspace_id).get(payload.connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    ingest_connection.delay(str(connection.id), TriggeredBy.MANUAL.value)
    return {"status": "queued", "connection_id": str(connection.id)}
