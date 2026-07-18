"""Structured Drive search - same philosophy as mail_query.py/calendar_query.py:
Drive's own search index does the work; nothing here calls the LLM.
"""

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
