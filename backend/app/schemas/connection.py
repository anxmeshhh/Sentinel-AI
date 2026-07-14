import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ConnectionCreate(BaseModel):
    org: str = Field(..., examples=["northwind"])
    repo: str = Field(..., examples=["checkout-service"])
    github_token: str = Field(
        ...,
        description="GitHub PAT with repo read scope. Encrypted at rest; never returned by the API.",
    )


class ConnectionOut(BaseModel):
    id: uuid.UUID
    org: str
    repo: str
    last_synced_at: datetime | None

    model_config = {"from_attributes": True}
