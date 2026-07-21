"""Phase 2z: manage connections shared at a Class or Group.

Same shape as the channel-connection routes (assign a workspace connection,
allow-list resources, unassign), one and two tiers up. RBAC follows the
hierarchy: Class connections are a workspace-admin concern (they become
context for every channel in the class); Group connections additionally
allow a team_manager, since a group is that role's remit.

The tenant boundary is the hard check everywhere: a connection must belong
to the same workspace as the class/group it's being shared into, exactly as
the channel tier enforces. A connection from another workspace is 404, never
assignable.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_workspace_role
from app.models.connection import Connection
from app.models.hierarchy import Group, WorkspaceClass
from app.models.shared_connection import SharedConnection, SharedConnectionResource, SharedScope
from app.models.user import User
from app.schemas.shared_connection import (
    SharedConnectionCreate,
    SharedConnectionOut,
    SharedConnectionResourceCreate,
    SharedConnectionResourceOut,
)
from app.services.hierarchy import CLASS_MANAGER_ROLES, GROUP_MANAGER_ROLES, get_class_in_workspace, get_group_in_class

router = APIRouter(tags=["shared-connections"])


def _to_out(shared: SharedConnection, connection: Connection, resources: list[SharedConnectionResource]) -> SharedConnectionOut:
    return SharedConnectionOut(
        id=shared.id,
        scope_type=shared.scope_type.value,
        scope_id=shared.scope_id,
        connection_id=connection.id,
        provider=connection.provider.value,
        label=connection.full_name,
        resources=[SharedConnectionResourceOut.model_validate(r) for r in resources],
    )


def _list_for_scope(session: Session, scope: SharedScope, scope_id: uuid.UUID) -> list[SharedConnectionOut]:
    rows = session.execute(
        select(SharedConnection, Connection)
        .join(Connection, Connection.id == SharedConnection.connection_id)
        .where(SharedConnection.scope_type == scope, SharedConnection.scope_id == scope_id)
    ).all()
    out = []
    for shared, connection in rows:
        resources = session.execute(
            select(SharedConnectionResource).where(SharedConnectionResource.shared_connection_id == shared.id)
        ).scalars().all()
        out.append(_to_out(shared, connection, list(resources)))
    return out


def _assign(session: Session, workspace_id: uuid.UUID, scope: SharedScope, scope_id: uuid.UUID, connection_id: uuid.UUID, user: User) -> SharedConnectionOut:
    connection = session.get(Connection, connection_id)
    if connection is None or connection.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Connection not found in this workspace")
    existing = session.execute(
        select(SharedConnection).where(
            SharedConnection.scope_type == scope, SharedConnection.scope_id == scope_id, SharedConnection.connection_id == connection_id
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="This connection is already shared here")
    shared = SharedConnection(scope_type=scope, scope_id=scope_id, connection_id=connection_id, added_by_user_id=user.id)
    session.add(shared)
    session.commit()
    session.refresh(shared)
    return _to_out(shared, connection, [])


def _resolve_shared(session: Session, scope: SharedScope, scope_id: uuid.UUID, shared_id: uuid.UUID) -> SharedConnection:
    shared = session.get(SharedConnection, shared_id)
    if shared is None or shared.scope_type != scope or shared.scope_id != scope_id:
        raise HTTPException(status_code=404, detail="Not found")
    return shared


def _add_resource(session: Session, shared: SharedConnection, payload: SharedConnectionResourceCreate) -> SharedConnectionResourceOut:
    existing = session.execute(
        select(SharedConnectionResource).where(
            SharedConnectionResource.shared_connection_id == shared.id,
            SharedConnectionResource.resource_key == payload.resource_key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="This resource is already allow-listed")
    resource = SharedConnectionResource(shared_connection_id=shared.id, resource_key=payload.resource_key, resource_label=payload.resource_label)
    session.add(resource)
    session.commit()
    session.refresh(resource)
    return SharedConnectionResourceOut.model_validate(resource)


# === Class-level ==========================================================


def _class_or_404(session: Session, workspace_id: uuid.UUID, class_id: uuid.UUID) -> WorkspaceClass:
    workspace_class = get_class_in_workspace(session, workspace_id, class_id)
    if workspace_class is None:
        raise HTTPException(status_code=404, detail="Class not found")
    return workspace_class


@router.get("/workspaces/{workspace_id}/classes/{class_id}/connections", response_model=list[SharedConnectionOut])
def list_class_connections(workspace_id: uuid.UUID, class_id: uuid.UUID, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_workspace_role(session, user, workspace_id, allowed=CLASS_MANAGER_ROLES)
    _class_or_404(session, workspace_id, class_id)
    return _list_for_scope(session, SharedScope.CLASS, class_id)


@router.post("/workspaces/{workspace_id}/classes/{class_id}/connections", response_model=SharedConnectionOut, status_code=201)
def assign_class_connection(workspace_id: uuid.UUID, class_id: uuid.UUID, payload: SharedConnectionCreate, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_workspace_role(session, user, workspace_id, allowed=CLASS_MANAGER_ROLES)
    _class_or_404(session, workspace_id, class_id)
    return _assign(session, workspace_id, SharedScope.CLASS, class_id, payload.connection_id, user)


@router.delete("/workspaces/{workspace_id}/classes/{class_id}/connections/{shared_id}", status_code=204)
def unassign_class_connection(workspace_id: uuid.UUID, class_id: uuid.UUID, shared_id: uuid.UUID, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_workspace_role(session, user, workspace_id, allowed=CLASS_MANAGER_ROLES)
    _class_or_404(session, workspace_id, class_id)
    session.delete(_resolve_shared(session, SharedScope.CLASS, class_id, shared_id))  # cascades resources
    session.commit()


@router.post("/workspaces/{workspace_id}/classes/{class_id}/connections/{shared_id}/resources", response_model=SharedConnectionResourceOut, status_code=201)
def add_class_resource(workspace_id: uuid.UUID, class_id: uuid.UUID, shared_id: uuid.UUID, payload: SharedConnectionResourceCreate, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_workspace_role(session, user, workspace_id, allowed=CLASS_MANAGER_ROLES)
    _class_or_404(session, workspace_id, class_id)
    return _add_resource(session, _resolve_shared(session, SharedScope.CLASS, class_id, shared_id), payload)


@router.delete("/workspaces/{workspace_id}/classes/{class_id}/connections/{shared_id}/resources/{resource_id}", status_code=204)
def remove_class_resource(workspace_id: uuid.UUID, class_id: uuid.UUID, shared_id: uuid.UUID, resource_id: uuid.UUID, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_workspace_role(session, user, workspace_id, allowed=CLASS_MANAGER_ROLES)
    _class_or_404(session, workspace_id, class_id)
    _resolve_shared(session, SharedScope.CLASS, class_id, shared_id)
    resource = session.get(SharedConnectionResource, resource_id)
    if resource is None or resource.shared_connection_id != shared_id:
        raise HTTPException(status_code=404, detail="Not found")
    session.delete(resource)
    session.commit()


# === Group-level ==========================================================


def _group_or_404(session: Session, workspace_id: uuid.UUID, class_id: uuid.UUID, group_id: uuid.UUID) -> Group:
    _class_or_404(session, workspace_id, class_id)
    group = get_group_in_class(session, class_id, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@router.get("/workspaces/{workspace_id}/classes/{class_id}/groups/{group_id}/connections", response_model=list[SharedConnectionOut])
def list_group_connections(workspace_id: uuid.UUID, class_id: uuid.UUID, group_id: uuid.UUID, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_workspace_role(session, user, workspace_id, allowed=GROUP_MANAGER_ROLES)
    _group_or_404(session, workspace_id, class_id, group_id)
    return _list_for_scope(session, SharedScope.GROUP, group_id)


@router.post("/workspaces/{workspace_id}/classes/{class_id}/groups/{group_id}/connections", response_model=SharedConnectionOut, status_code=201)
def assign_group_connection(workspace_id: uuid.UUID, class_id: uuid.UUID, group_id: uuid.UUID, payload: SharedConnectionCreate, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_workspace_role(session, user, workspace_id, allowed=GROUP_MANAGER_ROLES)
    _group_or_404(session, workspace_id, class_id, group_id)
    return _assign(session, workspace_id, SharedScope.GROUP, group_id, payload.connection_id, user)


@router.delete("/workspaces/{workspace_id}/classes/{class_id}/groups/{group_id}/connections/{shared_id}", status_code=204)
def unassign_group_connection(workspace_id: uuid.UUID, class_id: uuid.UUID, group_id: uuid.UUID, shared_id: uuid.UUID, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_workspace_role(session, user, workspace_id, allowed=GROUP_MANAGER_ROLES)
    _group_or_404(session, workspace_id, class_id, group_id)
    session.delete(_resolve_shared(session, SharedScope.GROUP, group_id, shared_id))
    session.commit()


@router.post("/workspaces/{workspace_id}/classes/{class_id}/groups/{group_id}/connections/{shared_id}/resources", response_model=SharedConnectionResourceOut, status_code=201)
def add_group_resource(workspace_id: uuid.UUID, class_id: uuid.UUID, group_id: uuid.UUID, shared_id: uuid.UUID, payload: SharedConnectionResourceCreate, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_workspace_role(session, user, workspace_id, allowed=GROUP_MANAGER_ROLES)
    _group_or_404(session, workspace_id, class_id, group_id)
    return _add_resource(session, _resolve_shared(session, SharedScope.GROUP, group_id, shared_id), payload)


@router.delete("/workspaces/{workspace_id}/classes/{class_id}/groups/{group_id}/connections/{shared_id}/resources/{resource_id}", status_code=204)
def remove_group_resource(workspace_id: uuid.UUID, class_id: uuid.UUID, group_id: uuid.UUID, shared_id: uuid.UUID, resource_id: uuid.UUID, session: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_workspace_role(session, user, workspace_id, allowed=GROUP_MANAGER_ROLES)
    _group_or_404(session, workspace_id, class_id, group_id)
    _resolve_shared(session, SharedScope.GROUP, group_id, shared_id)
    resource = session.get(SharedConnectionResource, resource_id)
    if resource is None or resource.shared_connection_id != shared_id:
        raise HTTPException(status_code=404, detail="Not found")
    session.delete(resource)
    session.commit()
