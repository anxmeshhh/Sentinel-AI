from pydantic import BaseModel


class DriveFileOut(BaseModel):
    id: str
    name: str
    mime_type: str | None
    modified_at: str | None
    url: str | None
    owner: str | None
    shared: bool
    size_bytes: int | None


class DriveAnalyticsOut(BaseModel):
    recent_files: list[DriveFileOut]
    shared_files: list[DriveFileOut]
    type_counts: dict[str, int]
    large_files: list[DriveFileOut]
    storage_used_bytes: int | None
    storage_limit_bytes: int | None
