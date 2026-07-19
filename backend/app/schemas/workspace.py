import uuid

from pydantic import BaseModel, Field


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    kind: str
    role: str

    model_config = {"from_attributes": True}


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class WorkspaceMemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: str
