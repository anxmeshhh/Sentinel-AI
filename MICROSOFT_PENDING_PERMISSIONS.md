# Microsoft 365 — pending Entra permissions

Every Microsoft **read** path is live and verified. Every **write** path is
built, tested and blocked on the same single step: Graph's read-only scopes
refuse writes, and the new scopes only take effect on re-consent.

## What to add

Azure portal → **Sentinel** app registration → **API permissions** →
**+ Add a permission** → **Microsoft Graph** → **Delegated permissions**:

| Permission | Unblocks | Verified needed by |
|---|---|---|
| `Mail.ReadWrite` | drafts, reply drafts, flag, read-state | live 403 on `POST /me/messages` |
| `Mail.Send` | sending mail (HIGH risk, irreversible) | required by `outlook.send` |
| `Calendars.ReadWrite` | create / edit / cancel events | live 403 on `POST /me/events` |
| `Tasks.ReadWrite` | create / edit / complete / delete tasks | live 403 on `POST /me/todo/.../tasks` |
| `Files.ReadWrite` | folders, text files, rename, move, delete | added preemptively |
| `Notes.ReadWrite` | create note, add to note | added preemptively |

Also still outstanding from Sprint 2 (Teams metadata, harmless if added now):
`Team.ReadBasic.All`, `Channel.ReadBasic.All`.

Then: **Sentinel → Personal → Connections → Microsoft 365 → Reconnect.**
One reconnect unblocks all eighteen write actions at once.

## Why a reconnect is required

A `refresh_token` grant can only return scopes that were already consented to.
Sentinel therefore does **not** send `scope` on refresh (doing so broke refresh
outright once — see `integrations/microsoft_auth.py`), which means a newly added
scope reaches the token only through a fresh consent.

## What is already verified live

- Outlook Mail — read, propose, confirm-first
- Outlook Calendar — read, propose, confirm-first (correct MEDIUM risk solo)
- Microsoft To Do — read (live from Graph), propose, confirm-first
- OneDrive — **browse and search verified against the real drive**
- OneNote — browse verified (account currently has 0 notebooks)

Every blocked write recorded `status=failed` with no verification, and undo was
correctly refused — the safety model has held under four real provider
rejections.
