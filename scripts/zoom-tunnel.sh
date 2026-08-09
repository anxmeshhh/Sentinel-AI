#!/usr/bin/env bash
# Start the HTTPS tunnel Zoom's OAuth callback needs, and wire it up.
#
# Why this exists: Zoom rejects http://localhost redirect URLs with error 4700,
# even when the app registers exactly that URL and is installed on the account -
# confirmed by direct test, not inferred. Every other provider's callback works
# on localhost untouched; this is Zoom's requirement alone.
#
# A cloudflared QUICK tunnel gets a new hostname every start, so the one manual
# step - pasting that hostname into the Zoom app - cannot be automated away.
# This script does everything around it: starts the tunnel, waits for the URL,
# writes it into .env, restarts the backend, and prints exactly what to paste.
#
# Usage:  bash scripts/zoom-tunnel.sh
# Stop:   kill the cloudflared process (or close the terminal it logs to).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
LOG="$ROOT/.zoom-tunnel.log"
CLOUDFLARED="${CLOUDFLARED:-cloudflared}"

command -v "$CLOUDFLARED" >/dev/null 2>&1 || {
  echo "cloudflared not found. Install it, or set CLOUDFLARED=/path/to/cloudflared" >&2
  exit 1
}

echo "Starting tunnel to http://localhost:8000 ..."
rm -f "$LOG"
"$CLOUDFLARED" tunnel --url http://localhost:8000 --no-autoupdate >"$LOG" 2>&1 &
TUNNEL_PID=$!

URL=""
for _ in $(seq 1 30); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 2
done

if [ -z "$URL" ]; then
  echo "Tunnel did not report a URL. See $LOG" >&2
  kill "$TUNNEL_PID" 2>/dev/null || true
  exit 1
fi

# Replace the existing value rather than appending, so repeated runs stay clean.
if grep -q '^ZOOM_REDIRECT_BASE_URL=' "$ENV_FILE"; then
  # A URL contains slashes, so use | as the sed delimiter.
  sed -i.bak "s|^ZOOM_REDIRECT_BASE_URL=.*|ZOOM_REDIRECT_BASE_URL=$URL|" "$ENV_FILE"
  rm -f "$ENV_FILE.bak"
else
  printf '\nZOOM_REDIRECT_BASE_URL=%s\n' "$URL" >>"$ENV_FILE"
fi

# `restart` does NOT re-read env_file - the container must be recreated.
echo "Recreating the backend so it picks up the new URL ..."
(cd "$ROOT" && docker compose up -d backend worker beat >/dev/null 2>&1) || {
  echo "Could not recreate the backend; run 'docker compose up -d backend' yourself." >&2
}

cat <<EOF

Tunnel is up  (pid $TUNNEL_PID, log: $LOG)

  ONE manual step - paste this into the Zoom app's
  Basic Information -> OAuth Information -> Redirect URL for OAuth,
  and into its OAuth Allow List, then Save:

      $URL/integrations/zoom/callback

  Then connect at http://localhost:5173/zoom

Leave this tunnel running. If it stops, the hostname changes and you will need
to paste a new one into Zoom.
EOF
