import uuid

from pydantic import BaseModel, Field


class ChannelConnectionResourceOut(BaseModel):
    id: uuid.UUID
    resource_key: str
    resource_label: str

    model_config = {"from_attributes": True}


class ChannelConnectionResourceCreate(BaseModel):
    resource_key: str = Field(..., min_length=1, max_length=500)
    resource_label: str = Field(..., min_length=1, max_length=300)


class ChannelConnectionOut(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    connection_id: uuid.UUID
    provider: str
    label: str  # Connection.full_name - never the raw org/repo/token fields
    resources: list[ChannelConnectionResourceOut]


class ChannelConnectionCreate(BaseModel):
    connection_id: uuid.UUID
