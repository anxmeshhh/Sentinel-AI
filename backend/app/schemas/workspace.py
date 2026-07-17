import uuid

from pydantic import BaseModel


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    kind: str

    model_config = {"from_attributes": True}
