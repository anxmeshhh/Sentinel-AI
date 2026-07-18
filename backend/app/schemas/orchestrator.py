from pydantic import BaseModel


class CommandRequest(BaseModel):
    command: str


class CommandResponse(BaseModel):
    status: str  # "done" | "confirmation_required" | "error"
    reply: str | None = None
    plan: dict | None = None
    pending_action: dict | None = None


class ExecuteActionRequest(BaseModel):
    name: str
    arguments: dict


class ExecuteActionResponse(BaseModel):
    result: dict
