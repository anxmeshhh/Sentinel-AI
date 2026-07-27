# Track A — the Connections ecosystem

Connections are infrastructure for intelligence, not the product. This file
exists so that finishing them is a checklist rather than a research project.

Every provider must plug into the pipeline already built. None of it is
re-designed per provider:

    CONNECT -> AUTHENTICATE -> AUTHORIZE RESOURCES -> EXPLICIT SHARE (workspace/class/group)
    -> CHANNEL INHERITANCE -> OPTIONAL EXCLUSIONS -> RBAC + RESOURCE PERMISSIONS
    -> SCOPED DATA -> ATTENTION + SENTINEL AI

---

## Status

| Provider | Auth | Data | Attention | AI | Shared/RBAC | Status |
|---|---|---|---|---|---|---|
| Google (Gmail, Calendar, Drive) | OAuth ✅ | ✅ | ✅ | ✅ | ✅ | **COMPLETE** ✅ |
| GitHub | OAuth ✅ | ✅ | ✅ | ✅ | ✅ | **COMPLETE** ✅ |
| Slack | — | — | — | — | — | **BLOCKED** 🔴 |
| Notion | — | — | — | — | — | **BLOCKED** 🔴 |
| Microsoft 365 | — | — | — | — | — | **BLOCKED** 🔴 |
| Jira | — | — | — | — | — | **BLOCKED** 🔴 |
| Zoom | — | — | — | — | — | **BLOCKED** 🔴 |

Everything below `GitHub` is blocked on **one thing only**: an OAuth
application that has to be registered by a human with an account on that
platform. No amount of code removes that step, and a provider is not built
until it has fetched real data from a real account — a client written against
the docs and never run is a guess with good syntax.

Google and GitHub credentials are configured. `microsoft_client_id` exists in
`Settings` but is empty, and is for *login* rather than for Outlook/OneDrive
data.

---

## What you need to create

Each block below is what unblocks one provider. Add the values to
`backend/.env`. All redirect URIs assume the current
`backend_base_url=http://localhost:8000`.

### 1. GitHub OAuth App — ✅ DONE

Registered and verified. Kept here as the reference for the other five.


<https://github.com/settings/developers> → **New OAuth App**

| Field | Value |
|---|---|
| Application name | Sentinel |
| Homepage URL | `http://localhost:5173` |
| Authorization callback URL | `http://localhost:8000/integrations/github/callback` |

```
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
```

Scopes to request: `repo` (private repo metadata) and `read:org`. Nothing
more — the client fetches metadata only and must never gain write access.

### 2. Slack app

<https://api.slack.com/apps> → **Create New App** → *From scratch*

- **OAuth & Permissions** → Redirect URL: `http://localhost:8000/integrations/slack/callback`
- Bot token scopes: `channels:history`, `channels:read`, `users:read`
- Install to workspace

```
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
SLACK_SIGNING_SECRET=...
```

### 3. Notion integration

<https://www.notion.so/my-integrations> → **New integration** → *Public* (OAuth)

- Redirect URI: `http://localhost:8000/integrations/notion/callback`

```
NOTION_CLIENT_ID=...
NOTION_CLIENT_SECRET=...
```

Note: Notion grants access **per page**, selected by the user during consent.
That maps directly onto the existing resource allow-list — Notion is
resource-scoped in the same way Drive is.

### 4. Microsoft 365 (Entra ID)

<https://entra.microsoft.com> → App registrations → **New registration**

- Redirect URI (Web): `http://localhost:8000/integrations/microsoft/callback`
- API permissions (delegated): `Mail.Read`, `Calendars.Read`, `Files.Read.All`, `offline_access`
- Certificates & secrets → **New client secret**

```
MICROSOFT_CLIENT_ID=...
MICROSOFT_CLIENT_SECRET=...
```

These same values also enable Microsoft *login*, which is already coded and
inert for want of them.

### 5. Jira (Atlassian OAuth 2.0 3LO)

<https://developer.atlassian.com/console/myapps/> → **Create** → *OAuth 2.0 integration*

- Callback URL: `http://localhost:8000/integrations/jira/callback`
- Scopes: `read:jira-work`, `read:jira-user`, `offline_access`

```
JIRA_CLIENT_ID=...
JIRA_CLIENT_SECRET=...
```

### 6. Zoom

<https://marketplace.zoom.us/develop/create> → **General App**

- Redirect URL: `http://localhost:8000/integrations/zoom/callback`
- Scopes: `meeting:read`, `recording:read`, `user:read`

```
ZOOM_CLIENT_ID=...
ZOOM_CLIENT_SECRET=...
```

---

## Recommended order, and why

1. ~~**GitHub OAuth**~~ — done. Fixed two live bugs: a revoked token reported
   `ready`, and the PAT route it replaced could not create a connection at all.
2. **Slack** — the largest genuine intelligence gain. Unanswered questions,
   stalled decisions and missing approvals are operational signals that exist
   in no other connected system.
3. **Microsoft 365** — the widest reach per unit of work. Outlook Mail and
   Calendar map onto detectors that already exist; for an org on Microsoft
   rather than Google it is the difference between Sentinel working and not.
4. **Jira** — highest signal-to-noise for operations: stalled tickets and
   unassigned work are unambiguous.
5. **Notion** — knowledge staleness is real but slower-moving, and Notion's
   per-page grants need care to map onto the allow-list.
6. **Zoom** — narrowest. Meetings are largely covered by Calendar already;
   the unique addition is recordings/transcripts.

Ordered by *operational intelligence per unit of work*, not by API pleasantness.

---

## What each provider should read — and what it must not

Deliberately narrow. The rule throughout the codebase is to retrieve only
useful, authorized context, never everything an API offers.

| Provider | Read | Detect / Attention | Never |
|---|---|---|---|
| GitHub | PR/commit/issue/review **metadata** | stale PRs, unreviewed changes | diffs, patches, file contents |
| Slack | messages in authorized channels | unanswered questions, stalled decisions, missing approvals | DMs, private channels |
| Notion | pages explicitly granted at consent | stale docs, duplication | any page not granted |
| Microsoft 365 | mail headers, calendar events, file metadata | same detectors as Gmail/Calendar | mail bodies at rest, file contents |
| Jira | issues, status, assignee, transitions | stalled tickets, unassigned work, missed due dates | comment bodies unless asked |
| Zoom | meetings, participants, recording metadata | meetings with no agenda/notes | recording media, transcripts at rest |

Two constraints hold for all of them, inherited rather than re-argued:

- **Bodies are fetched live, never stored.** Gmail stores headers only;
  Drive stores nothing. Anything new follows that.
- **Personal connections never reach a shared surface.** Enforced in the
  authorization layer and in attention (`attention_items.connection_id`),
  not in the frontend.

---

## The connector contract

`app/providers/registry.py` is the single description of what a provider
*is*. Before it, the same four providers were described by four separate
literals in four modules, and nothing forced them to agree.

Two of those literals — "ingests into Signals" and "queried live" — are
logical complements. They drifted exactly once, and that was enough: Drive
was in neither set, so `last_synced_at` stayed NULL forever, readiness
reported `syncing` forever, and channel setup could never complete. Every
module was individually self-consistent, so nothing failed. They are now one
field with two values, and a provider that declares neither fails at import.

### Adding a provider

1. A `Provider` enum member.
2. A `ProviderSpec` in the registry (retrieval, auth kind, signal types,
   whether it is resource-scoped).
3. A client in `app/integrations/`.
4. An ingest handler in `ingestion.py` — only if it ingests.

Nothing else enumerates providers by hand. Sharing, inheritance, exclusions,
RBAC, resource allow-lists, attention gating and AI scoping are all provider-
agnostic and come for free.

`ProviderSpec.revocation_observable` is what makes "an expired GitHub token
still reports ready" a stated property rather than a surprise: detecting a
dead connection requires a refresh that fails, which requires a refresh
token, which a pasted PAT does not have.

---

## GitHub: from one repo to a first-class multi-repo sense

Multi-repository, per-repo lifecycle, and real signal flow — built and
verified against the live GitHub API.

### One account, many repositories — each a full connection

A monitored repository is its own `Connection` row. That is the load-bearing
decision: every downstream system (signals, attention, channel sharing,
exclusions, investigation, goals) already keys on `connection_id`, so a
repo-as-connection flows through all of it unchanged and gains independent
behaviour for free — one repo can be shared to a channel and another kept
private, one paused, one investigated, without touching the rest. The
alternative (an account with a child repository table) would have meant
threading `repository_id` through every one of those systems. The unique key
moved from `(workspace, user, provider)` to `(workspace, user, provider,
repo)`; Google is unaffected (its services are distinct providers).

The OAuth token is one account's, stored redundantly per repo row, so
account events fan out: reconnect refreshes every row, a different account
replacing the old one wipes every row (`github_login` is what makes that
detectable — `org` holds a repo's *owner*, often an org the user only
collaborates in).

### Per-repository lifecycle

Add · remove · **pause** (keep history, stop syncing — skipped by both the
poll and direct ingestion) · **sync now** · and honest per-repo state:
`ready / syncing / error / paused / token_revoked / needs_setup`. `error`
exists because `last_success_at` is tracked separately from `last_synced_at`
— a connection that has tried and never succeeded looks recent by the latter
and is exposed as failing by the gap. `CONNECTING` and `OUTAGE` are
deliberately *not* stored states: the first has no row yet, the second is a
live-request property returned as a 502, and inventing stored versions would
claim knowledge the row does not hold.

### Backfill widened 30 → 90 days

Measured against the real account, every repository's most recent activity
was already 30–40 days old — a 30-day window started every new GitHub
connection empty. Dev work moves in weeks, not hours; the window now matches
the source.

### Real-data verification

Two repositories connected and synced against the live API:
**`growth-compass` → 22 commit signals, `opti-query-hub` → 16**, all
reachable in the personal scope and flowing into Feed, Insights and
Investigate through the same `connection_id` gate every provider uses. GitHub
is a sense feeding the engine, not a dashboard beside it.

Evidence is now rendered as structured cards with a **View raw data**
expander, rather than `JSON.stringify`.

### Honestly deferred — awaiting data or scope, not faked

- **Attention detectors beyond stale-PR.** This account produces only commits
  — no PRs, issues or CI runs — so PR-waiting / review-requested / issue-aging
  detectors cannot be *validated* against real data. The existing stale-PR
  detector stands; new ones wait for real PR/issue activity rather than being
  shipped unfireable. (A data-quality note for later: many commits here are
  `lovable-dev[bot]`, so a human-vs-bot distinction will matter.)
- **Workflows / CI failures, security & Dependabot alerts, releases, tags,
  branch events.** Not fetched; several need scopes (`actions:read`,
  `security_events`) this OAuth App does not request. The signal-type
  architecture is ready for them.
- **Webhooks / real-time.** Polling only for now.

---

## The Provider Contract

Every provider — Google and GitHub today, Slack/Jira/Notion/Microsoft/Zoom
later — implements the same lifecycle. This is not a new framework to build;
it is the shape the existing pieces already form, written down so that adding
a provider is filling in a contract rather than inventing a structure.

```
Provider
│
├── Connection      one Connection row per (workspace, user, provider, resource);
│                   the OAuth grant lives here (routes/integrations.py)
├── Resources       what is watched - a mailbox, a repository, a page. GitHub
│                   makes each resource its own Connection so it inherits the
│                   whole pipeline; per-provider detail lives in the resource
├── Sync            ingestion.py fetches since last sync; poll fans out per
│                   connection; paused connections are skipped
├── Signals         provider data normalized to Signal rows (SignalType), the
│                   one shape every intelligence module reads
├── Findings        attention items, proactive situations, commitments and
│                   goal evidence - all keyed on connection_id, so a provider
│                   feeds them by emitting signals, not by adding logic
├── History         the signals and findings a resource produced over time
├── Health          per-resource state (ready/syncing/error/paused/…), derived
│                   from stored timestamps + revocation, never guessed
├── Classification  ResourcePriority - the human context that decides whether
│                   activity-based attention fires (critical repo gone quiet)
└── Settings        add / remove / pause / reconnect / classify per resource
```

The load-bearing rule underneath it: **a provider contributes intelligence by
emitting normalized signals, never by adding provider-specific logic through
the app.** GitHub's stalled-critical-repo detector reads Signals and a
priority flag; it does not teach attention, goals or investigation anything
about GitHub. That is what keeps the intelligence engine provider-agnostic,
and what will let the sixth provider plug in without touching the first five.

### Repository (resource) classification

`ResourcePriority` — CRITICAL / NORMAL / LOW / ARCHIVED / EXPERIMENTAL — is
the contract's answer to "silence alone is not a finding." Most quiet
repositories are simply finished; alerting on all of them is noise. A person
marking one CRITICAL supplies the judgment the data cannot, and only then
does its silence become a proactive situation (`REPO_STALLED`). The levels are
provider-agnostic by design — the same field will weight a Jira project or a
Slack channel when they arrive.

**Real-data verified:** a real repository silent 46 days produces zero
findings at NORMAL and one at CRITICAL, resolving on its own the moment
commits resume.
