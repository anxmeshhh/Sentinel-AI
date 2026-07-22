import uuid

from pydantic import BaseModel, Field


class SharedConnectionResourceOut(BaseModel):
    id: uuid.UUID
    resource_key: str
    resource_label: str

    model_config = {"from_attributes": True}


class SharedConnectionResourceCreate(BaseModel):
    resource_key: str = Field(..., min_length=1, max_length=500)
    resource_label: str = Field(..., min_length=1, max_length=300)


class SharedConnectionOut(BaseModel):
    id: uuid.UUID
    scope_type: str
    scope_id: uuid.UUID
    connection_id: uuid.UUID
    provider: str
    label: str  # Connection.full_name - never raw token fields
    resources: list[SharedConnectionResourceOut]


class SharedConnectionCreate(BaseModel):
    connection_id: uuid.UUID


class ChannelExclusionCreate(BaseModel):
    connection_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=300)


class ChannelExclusionOut(BaseModel):
    """A connection this channel has opted out of. Carries no token and no
    resources - an exclusion grants nothing, it only subtracts."""

    id: uuid.UUID
    connection_id: uuid.UUID
    provider: str
    label: str
    reason: str | None
