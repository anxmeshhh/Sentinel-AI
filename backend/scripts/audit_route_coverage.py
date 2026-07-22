"""Which backend capabilities can a user actually reach?

Reads the live OpenAPI spec, then greps the frontend for a caller of each
path. A route with no caller is not necessarily a bug - some exist for the
OAuth redirect flow, or are called by other services - but every one needs a
reason, and this is the list that forces the question to be asked.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

FRONTEND = Path("/frontend_src")

# Paths that legitimately have no frontend caller.
EXPECTED_SERVERSIDE = {
    "/health",
    "/integrations/google/connect",
    "/integrations/google/callback",
    "/auth/google/login",
    "/auth/google/callback",
    "/auth/microsoft/login",
    "/auth/microsoft/callback",
}


def template_to_regex(path: str) -> re.Pattern:
    """`/teams/{team_id}/goals` -> something that matches a template literal."""
    parts = re.split(r"\{[^}]+\}", path)
    escaped = [re.escape(p) for p in parts]
    return re.compile(r"\$\{[^}]*\}".join(escaped) if len(escaped) > 1 else escaped[0])


def main() -> int:
    spec = json.loads(sys.stdin.read())
    sources = []
    for ext in ("*.ts", "*.tsx"):
        sources.extend(FRONTEND.rglob(ext))
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in sources)

    uncalled = []
    for path, methods in sorted(spec["paths"].items()):
        if path in EXPECTED_SERVERSIDE:
            continue
        if template_to_regex(path).search(blob):
            continue
        uncalled.append((path, sorted(m.upper() for m in methods)))

    print(f"{len(spec['paths'])} routes in the API")
    print(f"{len(uncalled)} with no frontend caller\n")
    for path, methods in uncalled:
        print(f"  {','.join(methods):18} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
