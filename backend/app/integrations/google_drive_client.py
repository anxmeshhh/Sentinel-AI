"""Google Drive client - metadata/search only, same read-only, least-
privilege posture as every other client here. Never downloads or returns
file content - only enough to identify a file and link out to it. Sentinel
links to Drive; it never renders a Drive file itself (per the "external
resources are always a link out, never opened inside Sentinel" rule).
"""

import httpx
import structlog

logger = structlog.get_logger("sentinel.google_drive")

API_BASE = "https://www.googleapis.com/drive/v3"
FIELDS = "files(id,name,mimeType,modifiedTime,webViewLink,iconLink,owners(displayName),shared)"


class GoogleDriveClient:
    def __init__(self, access_token: str, timeout: float = 20.0):
        self._client = httpx.Client(base_url=API_BASE, headers={"Authorization": f"Bearer {access_token}"}, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GoogleDriveClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def search(self, query: str, max_results: int = 20) -> list[dict]:
        params = {"q": query, "fields": FIELDS, "orderBy": "modifiedTime desc", "pageSize": min(max_results, 100)}
        resp = self._client.get("/files", params=params)
        if resp.status_code >= 400:
            logger.warning("drive_search_failed", status=resp.status_code, body=resp.text[:500])
            resp.raise_for_status()
        return [_normalize_file(f) for f in resp.json().get("files", [])]


def _normalize_file(f: dict) -> dict:
    owners = f.get("owners") or []
    return {
        "id": f["id"],
        "name": f.get("name", "(untitled)"),
        "mime_type": f.get("mimeType"),
        "modified_at": f.get("modifiedTime"),
        "url": f.get("webViewLink"),
        "owner": owners[0].get("displayName") if owners else None,
        "shared": bool(f.get("shared", False)),
    }
