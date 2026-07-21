from pydantic import BaseModel


class CommandRequest(BaseModel):
    command: str


class CommandResponse(BaseModel):
    status: str  # "done" | "confirmation_required" | "error"
    reply: str | None = None
    plan: dict | None = None
    pending_action: dict | None = None
    # Compact navigable citations from the read tools that actually ran -
    # {kind, title, meta, url}. The UI renders these as a Sources block
    # instead of hoping the model linked everything in prose.
    sources: list[dict] = []


class ExecuteActionRequest(BaseModel):
    name: str
    arguments: dict


class ExecuteActionResponse(BaseModel):
    result: dict
