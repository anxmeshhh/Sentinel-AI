"""Shared slug generation for Workspaces and Teams."""

import re
import secrets


def unique_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "untitled"
    return f"{base}-{secrets.token_hex(3)}"
