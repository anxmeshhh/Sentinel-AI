"""Workspace-scoped repository base.

This is a security boundary, not just a convenience: every read/write in the
app goes through a repository bound to one workspace_id, so it is structurally
impossible to write a query that forgets to scope by tenant. Routes and agents
never touch `session.query(...)` directly for workspace-owned tables.
"""

import uuid
from typing import Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class WorkspaceScopedRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: Session, workspace_id: uuid.UUID):
        self.session = session
        self.workspace_id = workspace_id

    def _scoped(self) -> Select:
        return select(self.model).where(self.model.workspace_id == self.workspace_id)

    def get(self, id_: uuid.UUID) -> ModelT | None:
        return self.session.execute(self._scoped().where(self.model.id == id_)).scalar_one_or_none()

    def add(self, obj: ModelT) -> ModelT:
        obj.workspace_id = self.workspace_id
        self.session.add(obj)
        return obj
