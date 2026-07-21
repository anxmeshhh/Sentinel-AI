"""Structured Drive search - same philosophy as mail_query.py/calendar_query.py:
Drive's own search index does the work; nothing here calls the LLM.
"""

from app.integrations.google_auth import get_valid_access_token
from app.integrations.google_drive_client import GoogleDriveClient
from app.models.connection import Provider
from app.repositories.connections import ConnectionRepository

MIME_TYPE_ALIASES = {
    "pdf": "application/pdf",
    "doc": "application/vnd.google-apps.document",
    "document": "application/vnd.google-apps.document",
    "sheet": "application/vnd.google-apps.spreadsheet",
    "spreadsheet": "application/vnd.google-apps.spreadsheet",
    "slide": "application/vnd.google-apps.presentation",
    "presentation": "application/vnd.google-apps.presentation",
    "folder": "application/vnd.google-apps.folder",
}


def build_drive_query(
    *,
    keywords: str | None = None,
    mime_type: str | None = None,
    modified_after: str | None = None,
    shared_with_me: bool | None = None,
) -> str:
    parts = ["trashed=false"]
    if keywords:
        escaped = keywords.replace("\\", "\\\\").replace("'", "\\'")
        parts.append(f"(fullText contains '{escaped}' or name contains '{escaped}')")
    if mime_type:
        mapped = MIME_TYPE_ALIASES.get(mime_type.lower())
        if mapped:
            parts.append(f"mimeType='{mapped}'")
    if modified_after:
        parts.append(f"modifiedTime > '{_to_rfc3339(modified_after)}'")
    if shared_with_me:
        parts.append("sharedWithMe=true")
    return " and ".join(parts)


def _to_rfc3339(date_str: str) -> str:
    return date_str if "T" in date_str else f"{date_str}T00:00:00"


def get_drive_analytics(session, workspace_id) -> dict | None:
    """Only reports what Drive's API genuinely provides - recent/shared
    files and type counts from real search results, storage usage from
    Drive's own about.get. No fabricated capability (no per-file view
    counts, no access history - Drive's API doesn't expose those).
    """
    connection = ConnectionRepository(session, workspace_id).get_for_user(user_id, Provider.GOOGLE_DRIVE)
    if connection is None:
        return None

    access_token = get_valid_access_token(session, connection)
    with GoogleDriveClient(access_token) as client:
        recent = client.search(build_drive_query(), max_results=10)
        shared = client.search(build_drive_query(shared_with_me=True), max_results=10)
        sample = client.search(build_drive_query(), max_results=100)
        quota = client.get_storage_quota()

    type_counts: dict[str, int] = {}
    for f in sample:
        mt = f.get("mime_type") or "unknown"
        type_counts[mt] = type_counts.get(mt, 0) + 1

    large_files = sorted((f for f in sample if f.get("size_bytes")), key=lambda f: f["size_bytes"], reverse=True)[:5]

    return {
        "recent_files": recent,
        "shared_files": shared,
        "type_counts": type_counts,
        "large_files": large_files,
        "storage_used_bytes": int(quota["usage"]) if quota.get("usage") else None,
        "storage_limit_bytes": int(quota["limit"]) if quota.get("limit") else None,
    }
