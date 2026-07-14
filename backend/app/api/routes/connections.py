import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_workspace_id
from app.core.security import encrypt_token
from app.models.connection import Connection, Provider
from app.repositories.connections import ConnectionRepository
from app.schemas.connection import ConnectionCreate, ConnectionOut

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("", response_model=list[ConnectionOut])
def list_connections(
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> list[Connection]:
    return ConnectionRepository(session, workspace_id).list_all()


@router.post("", response_model=ConnectionOut, status_code=201)
def create_connection(
    payload: ConnectionCreate,
    session: Session = Depends(get_db),
    workspace_id: uuid.UUID = Depends(get_workspace_id),
) -> Connection:
    # ConnectionOut deliberately has no token field - the plaintext token
    # never round-trips back out of this API once submitted.
    connection = Connection(
        provider=Provider.GITHUB,
        org=payload.org,
        repo=payload.repo,
        encrypted_token=encrypt_token(payload.github_token),
    )
    ConnectionRepository(session, workspace_id).add(connection)
    session.commit()
    session.refresh(connection)
    return connection


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
