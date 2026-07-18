from pydantic import BaseModel


class DriveFileOut(BaseModel):
    id: str
    name: str
    mime_type: str | None
    modified_at: str | None
    url: str | None
    owner: str | None
    shared: bool
