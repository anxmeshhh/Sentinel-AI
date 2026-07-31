import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_workspace_id
from app.models.connection import Connection
from app.repositories.connections import ConnectionRepository
from app.schemas.connection import ConnectionOut
from app.services.connection_state import connection_state

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("", response_model=list[ConnectionOut])
def list_connections(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list[ConnectionOut]:
    # Real health rides along, so callers (the connection cards) reflect the
    # true state rather than a mere "a row exists" boolean.
    return [
        ConnectionOut(
            id=c.id, provider=c.provider.value, org=c.org, repo=c.repo,
            last_synced_at=c.last_synced_at, state=connection_state(c).value,
        )
        for c in ConnectionRepository(session, workspace_id).list_all()
    ]


# POST /connections was removed in Phase 2.
#
# It created a GitHub connection from a pasted personal access token, and it
# had been failing since connections became per-user: it never set `user_id`,
# which is NOT NULL, so every submission died on an integrity error. Nobody
# could have used it, which is why this database holds no GitHub signals at
# all.
#
# GitHub is connected through OAuth now (see routes/integrations.py), which
# also gives it the thing a pasted token never could: credentials of
# Sentinel's own to ask GitHub whether the grant is still valid, so a revoked
# connection reports `expired` instead of quietly reporting `ready`.


@router.delete("/{connection_id}", status_code=204)
def delete_connection(
    connection_id: uuid.UUID,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> None:
    connection = ConnectionRepository(session, workspace_id).get(connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    session.delete(connection)
    session.commit()
