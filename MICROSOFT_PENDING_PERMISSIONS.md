# Microsoft 365 — permissions and live-verification status

**All required Graph permissions are granted, and every write path across all
five available services is verified live.** Nothing here is pending.

## Granted delegated scopes (each confirmed empirically, not assumed)

| Permission | Unblocks | Verified by |
|---|---|---|
| `Mail.ReadWrite` | drafts, reply drafts, flag, read-state | live `POST /me/messages` → 201 |
| `Mail.Send` | sending (HIGH risk, irreversible) | registered; see note below |
| `Calendars.ReadWrite` | create / edit / cancel events | live `POST /me/events` → 201 |
| `Tasks.ReadWrite` | create / edit / complete / delete tasks | live `POST /me/todo/…/tasks` → 201 |
| `Files.ReadWrite` | folders, text files, rename, move, delete | live `POST /me/drive/root/children` → 201 |
| `Notes.ReadWrite` | notebooks, sections, pages, appends | live create notebook/section/page → 201 |
| `Team.ReadBasic.All`, `Channel.ReadBasic.All` | Teams metadata | blocked by account type, not permission |

The access token is opaque (a personal Microsoft account issues no JWT), so
scopes cannot be read from the token — every entry above was proven by making
the actual call.

## Live verification — what has genuinely run against the real account

| Service | Read | Write | Undo |
|---|---|---|---|
| Outlook Mail | ✅ | ✅ draft created in the real mailbox | ✅ draft removed |
| Outlook Calendar | ✅ | ✅ event created, then edited | ✅ edit reverted, event deleted |
| Microsoft To Do | ✅ | ✅ task created, completed | ✅ reopened, task deleted |
| OneDrive | ✅ browse, search, navigate | ✅ folder, text file, rename, move, delete | ✅ rename + move reverted; delete correctly REFUSED |
| OneNote | ✅ | ✅ notebook, section, page, append | ✅ append reverted |

## Still unavailable — account type, not permission

Teams, SharePoint and Planner need a licensed Microsoft 365 Business /
Enterprise / Education tenant. Graph answers `/me/joinedTeams` with
`401 "requires a valid license"` on a personal account. No permission grant
changes this; it needs a work/school account.

## Sending mail

`outlook.send` is registered and available: HIGH risk, IRREVERSIBLE, confirmed
every time, with **no undo button** because none could work. It has NOT been
fired against the real mailbox — sending is the one action whose test cannot be
cleaned up afterwards.

## Note on refresh

Sentinel does not send `scope` when refreshing a token. A `refresh_token` grant
can only return already-consented scopes, and asking for more makes Entra reject
the whole refresh — which once caused a live connection to be wrongly marked
revoked. Adding a scope therefore takes effect on the next consent, not the next
refresh.
