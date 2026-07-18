"""Google Drive client - metadata/search only for browsing (never file
content there - see module-level note on fetch_file_content below, the one
deliberate exception, same discipline as GmailClient.fetch_message_body).
Sentinel links to Drive for the file itself; it never renders or recreates
the original resource (per the "external resources are always a link out,
never opened inside Sentinel" rule) - fetch_file_content exists only to let
the AI *reason about* a file's content on request, not to display it.
"""

import io

import httpx
import structlog
from docx import Document as DocxDocument
from pypdf import PdfReader

logger = structlog.get_logger("sentinel.google_drive")

API_BASE = "https://www.googleapis.com/drive/v3"
FIELDS = "files(id,name,mimeType,modifiedTime,webViewLink,iconLink,owners(displayName),shared,size)"

# Bounded by the orchestrator's actual rate-limit ceiling, not an arbitrary
# "reasonable" number: Groq's on-demand tier caps openai/gpt-oss-120b at
# 8000 tokens/minute for the *whole* request (system prompt + tool schemas +
# every message so far). System prompt + tool schemas alone already cost
# ~2500 tokens, so multi-file workflows (cross-document search, comparison,
# meeting prep) need real headroom left for 2-3 files in one loop, not just
# one - a single 20_000-char file (~5000 tokens) blew the whole budget by
# itself and made every composite Drive workflow fail with a 413. Confirmed
# via a real "which documents mention X" request against the account.
MAX_CONTENT_CHARS = 6_000

# Google-native formats exported as text via Drive's export endpoint - not a
# real download, this file_id "is" a Doc/Sheet/Slide, has no other stored form.
EXPORTABLE_MIME_TYPES = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
}

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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

    def fetch_file_content(self, file_id: str) -> tuple[str | None, str]:
        """Live, on-demand, never-persisted content read - only for the AI
        to reason about when a user explicitly asks something that needs
        it (summarize, extract deadlines, compare). Returns
        (content, mime_type) on success, or (None, human-readable reason)
        for file types Sentinel doesn't read (images, unknown binaries -
        Sentinel only ever reads text, never renders a file visually).
        """
        meta_resp = self._client.get(f"/files/{file_id}", params={"fields": "name,mimeType"})
        meta_resp.raise_for_status()
        mime_type = meta_resp.json().get("mimeType", "")

        if mime_type in EXPORTABLE_MIME_TYPES:
            export_mime = EXPORTABLE_MIME_TYPES[mime_type]
            resp = self._client.get(f"/files/{file_id}/export", params={"mimeType": export_mime})
            if resp.status_code >= 400:
                logger.warning("drive_export_failed", file_id=file_id, status=resp.status_code)
                return None, "Couldn't export this file's content."
            return resp.text[:MAX_CONTENT_CHARS], mime_type

        if mime_type == "application/pdf":
            resp = self._client.get(f"/files/{file_id}", params={"alt": "media"})
            if resp.status_code >= 400:
                logger.warning("drive_download_failed", file_id=file_id, status=resp.status_code)
                return None, "Couldn't download this PDF."
            try:
                reader = PdfReader(io.BytesIO(resp.content))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception:
                logger.warning("drive_pdf_extract_failed", file_id=file_id)
                return None, "Couldn't extract text from this PDF - it may be scanned/image-based."
            return text[:MAX_CONTENT_CHARS], mime_type

        if mime_type == DOCX_MIME_TYPE:
            resp = self._client.get(f"/files/{file_id}", params={"alt": "media"})
            if resp.status_code >= 400:
                logger.warning("drive_download_failed", file_id=file_id, status=resp.status_code)
                return None, "Couldn't download this Word document."
            try:
                doc = DocxDocument(io.BytesIO(resp.content))
                text = "\n".join(p.text for p in doc.paragraphs if p.text)
            except Exception:
                logger.warning("drive_docx_extract_failed", file_id=file_id)
                return None, "Couldn't extract text from this Word document."
            return text[:MAX_CONTENT_CHARS], mime_type

        if mime_type.startswith("text/"):
            resp = self._client.get(f"/files/{file_id}", params={"alt": "media"})
            if resp.status_code >= 400:
                return None, "Couldn't download this file."
            return resp.text[:MAX_CONTENT_CHARS], mime_type

        return None, f"Sentinel can only read text-based files (Docs, Sheets, Slides, PDF, Word, plain text) - this is {mime_type or 'an unsupported type'}."

    def get_storage_quota(self) -> dict:
        """Real usage/limit from Drive's own about.get - only claiming what
        the API genuinely reports, never a fabricated number."""
        resp = self._client.get("/about", params={"fields": "storageQuota"})
        resp.raise_for_status()
        return resp.json().get("storageQuota", {})


def _normalize_file(f: dict) -> dict:
    owners = f.get("owners") or []
    size = f.get("size")  # absent for native Google Docs/Sheets/Slides, present for binary files
    return {
        "id": f["id"],
        "name": f.get("name", "(untitled)"),
        "mime_type": f.get("mimeType"),
        "modified_at": f.get("modifiedTime"),
        "url": f.get("webViewLink"),
        "owner": owners[0].get("displayName") if owners else None,
        "shared": bool(f.get("shared", False)),
        "size_bytes": int(size) if size else None,
    }
