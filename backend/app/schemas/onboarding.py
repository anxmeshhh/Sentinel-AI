import uuid
from datetime import datetime

from pydantic import BaseModel


class OnboardingStateOut(BaseModel):
    persona: str | None
    onboarded_at: datetime | None
    suggested_providers: list[str]  # what this persona should connect first
    show_channels: bool  # whether Group/Channel surfaces are emphasized


class OnboardingUpdate(BaseModel):
    persona: str  # individual | developer | team | business | explorer


class DemoWorkspaceOut(BaseModel):
    workspace_id: uuid.UUID
    name: str
    signals_seeded: int
