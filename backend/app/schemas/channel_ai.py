import uuid
from datetime import datetime

from pydantic import BaseModel


class ChannelAIHistoryOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    command: str
    reply: str
    created_at: datetime
