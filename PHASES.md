# Sentinel AI — Execution Pipeline

This is the single build pipeline: it takes what `PRD.md`, `ARCHITECTURE.md`, `ROADMAP.md`, and
`IA.md` each described in their own dimension (why, how, when, what-it-looks-like) and turns it
into one ordered sequence of concrete build steps, so the whole system can be read top to bottom
before a single line of implementation code exists.

**Pipeline rule:** no phase starts until the previous phase's exit criteria are met **and** you've
given an explicit go-ahead. Docs get pushed to `main` at the end of every phase (and at meaningful
checkpoints inside a phase) so there's always a reviewable record — nothing sits unpushed.

---

## Phase 0 — Planning ✅ Done

- `PRD.md` — problem, vision, MVP scope, requirements, success metrics, risks
- `ARCHITECTURE.md` — stack rationale, data model, agent contract, LangGraph orchestration
- `ROADMAP.md` — high-level phase sequencing for all 10 agents
- `IA.md` — workspace-centric IA, RBAC matrix, agent page contract
- Two interactive artifacts reviewed and approved: product walkthrough, IA explorer

All pushed to `main`. **You are here.**

---

## Phase 1 — MVP Core Loop ✅ Built and smoke-tested

**Objective:** one connected GitHub repo produces one real, trusted finding, surfaced in a working
dashboard. Everything else in the system is inert until this loop is proven.

**IA surface that went live:** the Organization Workspace nav (`IA.md` §2.4), with only what's
built actually shown — Dashboard (Today's Brief), Agent Center (Engineering + Executive only),
Settings (Connections). Personal Workspace, Team Workspace, RBAC, and the other 7 agents stay
hidden, not partially built.

| Step | Deliverable | Status |
|---|---|---|
| 1.1 | Backend scaffold | ✅ |
| 1.2 | GitHub integration client | ✅ |
| 1.3 | Engineering Agent | ✅ |
| 1.4 | Groq LLM client | ✅ |
| 1.5 | Executive Agent + LangGraph orchestrator | ✅ |
| 1.6 | FastAPI endpoints + Celery beat | ✅ |
| 1.7 | React dashboard | ✅ |
| 1.8 | Local dev + smoke test | ✅ — passed against real MySQL + real Groq, both in a plain venv and in the full `docker compose` stack |

### What actually got built (technical notes)

**Two decisions changed mid-build, both reflected everywhere (code + docs):**
- **Database: MySQL, not Postgres.** You're running MySQL locally, so the whole data layer uses
  SQLAlchemy's backend-agnostic types (`sqlalchemy.Uuid`, `sqlalchemy.JSON`) instead of
  Postgres-only `UUID`/`JSONB`/`ARRAY`. The signal-dedup upsert uses MySQL's
  `INSERT ... ON DUPLICATE KEY UPDATE` instead of Postgres's `ON CONFLICT`. `ARCHITECTURE.md` §2–3
  and §8 are updated to match.
- **LLM: `openai/gpt-oss-120b` via Groq**, not Llama — one-line change in `agents/llm.py` and
  `.env`, because the provider is isolated behind a single client with zero LangChain coupling.

**Backend structure** (`backend/app/`): `core/` (config, structured logging, Fernet token
encryption, Celery app), `models/` (SQLAlchemy ORM: `Workspace`, `Membership`, `Connection`,
`Signal`, `AgentRun`, `Finding`, `Brief`), `repositories/` (every query goes through a
`WorkspaceScopedRepository` bound to one `workspace_id` — see below), `integrations/`
(`github_client.py`), `agents/` (`llm.py`, `engineering_agent.py`, `executive_agent.py`,
`graph.py`), `services/` (`ingestion.py`, `agent_orchestration.py` — the glue between DB, GitHub,
and the agent graph), `api/routes/`, `workers/tasks.py`. `alembic/` holds the one migration
(`initial schema`) generated and applied against your real local MySQL.

**Security/observability decisions from our earlier chat are actually in the code, not just the
docs:**
- `WorkspaceScopedRepository` — every read/write is bound to one `workspace_id` at construction;
  there's no code path that can query a workspace-owned table without that scope.
- `core/security.py` — GitHub tokens are Fernet-encrypted before hitting the `connections` table;
  the `ConnectionOut` API schema has no token field, so plaintext never round-trips back out.
- `core/logging.py` — structured JSON logs, with `run_id`/`workspace_id`/`agent` bound to every
  line for the duration of a run (`bind_run_context`), and a redaction processor that scrubs
  token-shaped keys before they'd ever hit a log line.
- `agent_runs.status` has a `partial` state — one specialist agent failing doesn't take down the
  whole run; the Brief gets a `data_freshness` note instead of silently going stale. This was
  proven for real during the smoke test, not just designed on paper (see below).

**Engineering Agent's real design (worth understanding, not just "it calls an LLM"):**
detection is deterministic Python, not the model. The agent computes real candidates first —
review-latency trend vs. baseline, single-dominant-reviewer hotspot directories, contributor
activity drop-off, fast+large+unreviewed merges to `main` — each with real evidence (PR numbers,
URLs, timestamps) attached. The LLM is only asked to narrate and score confidence for candidates
that already exist, matched back by index. This means a Finding's evidence is always traceable to
real ingested rows; the model can't hallucinate a finding that has no basis in the data, only
misjudge how important a real signal is (which the confidence threshold then filters).

**GitHub client**: metadata only, enforced in code — `fetch_pr_changed_dirs` explicitly discards
GitHub's `patch` field (the actual diff hunk) and keeps only filenames. Rate-limit aware: backs off
before hitting GitHub's floor, retries transient 5xx with backoff.

**Three real bugs the smoke test caught (this is why the smoke test step matters, not just a
checkbox):**
1. **PR state-transition duplication.** Signals were originally typed `pr_opened`/`pr_merged`; since
   the idempotency key includes `type`, a PR merging after being ingested as "open" would insert a
   *second* row instead of updating the first. Fixed by using a single `PR` signal type with state
   inside the payload.
2. **MySQL silently drops timezone info.** `datetime.now(timezone.utc) - signal.occurred_at` threw
   `can't subtract offset-naive and offset-aware datetimes` the first time the Engineering Agent
   actually ran against MySQL-stored signals (Postgres wouldn't have hit this — its `timestamptz`
   preserves tzinfo). Fixed with a custom `UTCDateTime` `TypeDecorator` (`models/base.py`) that
   normalizes every datetime to aware-UTC on the way out, once, for every model, instead of patching
   every call site. The `partial` run status meant this bug produced a clean "engineering agent
   failed, here's why" instead of a crash — which is exactly what that design was for.
3. **Celery serializes task args as JSON.** A `connection_id` passed to `.delay()` arrives in the
   task as a plain `str`, but `session.get(Connection, connection_id)` needs a real `uuid.UUID` for
   the `Uuid` column type. Fixed by parsing it back to `uuid.UUID` at the top of each task.

**Frontend** (`frontend/`): Vite + React + TypeScript + Tailwind, dark-first design carried over
directly from the approved walkthrough artifact (ink-navy ground, signal-teal accent, mono+sans
pairing, severity colors kept semantically separate from the brand accent). Five real pages wired
to the live API: `BriefPage` (today's brief + re-run), `FindingDetailPage` (evidence drill-down,
generic enough to render any agent's evidence shape), `HistoryPage`, `SettingsPage` (connections +
static agent roster reflecting phase gating). Type-checks clean, builds clean.

**Verified end-to-end, twice** — once in a plain Python venv against your local MySQL + real Groq
API (seeded seed signals reproducing the exact walkthrough scenario: the `auth/` review bottleneck
and the risky `main` merge), and once through the full `docker compose` stack (backend, worker,
beat, redis, frontend all in containers, backend reaching your host MySQL via
`host.docker.internal`). Both produced correct, real Groq-generated findings and a correct brief.

### Addendum: Admin & Observability panel

Added after initial Phase 1 completion, at your request, to actually *see* what the system is
doing rather than just trusting it. This is an **operator surface, not part of the customer-facing
IA** (`IA.md` has no "Admin" page under any workspace) — it's for whoever runs the Sentinel
instance itself, styled with a visually distinct nav group ("Operator", blue dot) so it doesn't
blend into the product pages above it.

- **`GET /admin/stats`** — live counts: connections, signals, findings, briefs, and a breakdown of
  run outcomes (success/partial/failed/running).
- **`GET /admin/runs`** — every `agent_runs` row, joined with its connection label and finding
  count, so you can see exactly when each run happened, how long it took, and what (if anything)
  went wrong (`node_errors`/`error`).
- **`GET /admin/logs`** — tails the structured JSONL log file. This required a real fix: Celery
  workers/beat were never actually running our structured-logging setup — only the API process
  was (`configure_logging()` was only called from `main.py`'s lifespan). Fixed by hooking Celery's
  `setup_logging` signal (`core/celery_app.py`) so worker and beat processes install the exact same
  structlog pipeline instead of Celery's own plain-text logging. Logs now also persist to a
  rotating file (`backend/logs/sentinel.jsonl`, gitignored) in addition to stdout, both rendered
  through the same `structlog.stdlib.ProcessorFormatter` so the two outputs can never drift apart.
- Frontend `AdminPage.tsx`: stat tiles, a runs table, and a polling (5s, toggleable) log viewer —
  all real data, no mocking.

**Security note carried forward, not resolved here:** this panel has zero access control right now
because Phase 1 has no auth at all. Once Phase 2 lands real RBAC, this must move behind the Super
Admin role (`IA.md` §3) before Sentinel has more than one trusted operator — leaving it open in a
multi-tenant world would leak every workspace's logs and run history to any logged-in user.

### Known gaps (deliberately deferred, not oversights)

- **No real GitHub PAT tested yet** — ingestion logic is unit-tested and code-reviewed against the
  GitHub API shape, but the smoke test used seeded signals rather than a live token. Worth doing
  once you have a repo + PAT you want to point it at.
- **Ingestion failures aren't recorded in `agent_runs` yet** — only the agent-run step is; a
  failed ingestion currently surfaces in Celery/worker logs but not yet in the UI. Small addition
  when it matters.
- **No auth yet** — every request resolves to the single default workspace (`core/bootstrap.py`).
  This is intentional per `PHASES.md` Phase 1 scope, not a bug.
- **Frontend has no automated tests yet** — type-checking and a manual/API-level smoke test, no
  component tests. Worth adding before Phase 2 grows the UI surface.

**Exit criteria (from `PRD.md` §8):** 3 real repos connected (yours + 2 pilots); each produces at
least one finding the repo owner independently confirms is accurate.

**⏸ Wait for signal before Phase 1.5.**

---

## Phase 1.5 — Personal Workspace ✅ Built and smoke-tested

**Objective:** prove Sentinel works for an individual with no team behind them — the "for
themselves as well" case from your IA brief, on the smallest possible surface.

**IA surface that went live:** Personal Workspace (`IA.md` §2.2) — Dashboard (reused from Phase 1,
now workspace-aware) and AI Assistant. Timeline, Integrations (personal-account scope beyond
GitHub), Notifications, Profile, Tasks/Calendar/Insights are still deliberately stubbed — see Known
gaps below, they need Gmail/Calendar (your explicit next step) to mean anything real.

| Step | Deliverable | Status |
|---|---|---|
| 1.5.1 | Data model: `users`, `workspaces`, `memberships` | ✅ |
| 1.5.2 | Personal-scope GitHub connection | Deferred — reuses the same `Connection`/GitHub client Phase 1 already has, no code change needed; not yet exercised with a real personal-account token |
| 1.5.3 | Personal Dashboard | ✅ — same `BriefPage`/`HistoryPage`/`SettingsPage` components as Phase 1, now genuinely workspace-scoped instead of hardcoded to one workspace |
| 1.5.4 | AI Assistant (chat) | ✅ |
| 1.5.5 | Workspace switcher (UI) | ✅ — real Personal ⇄ Organization switching, not a mockup |

### What actually got built (technical notes)

**The core proof point:** Phase 1's `WorkspaceScopedRepository` design (every query bound to one
`workspace_id`) meant adding a second, real workspace required zero changes to any repository,
agent, or existing route — only three things needed to change: how a workspace gets *resolved* per
request, plus two genuinely new features (the switcher and the assistant).

- **`users` table**, minimal (`id`, `email`, `name`, no password yet) — real FK from
  `memberships.user_id`, which was previously just a bare UUID with no backing table.
- **`core/bootstrap.py`** now provisions *two* workspaces for the single implicit Phase-1 user
  (Personal + the original Organization), each with a real `Membership` row — not a placeholder,
  an actual second tenant that proves the architecture generalizes.
- **`GET /workspaces`** lists both; **`get_workspace_id`** (`api/deps.py`) now reads an
  `X-Workspace-Id` header and validates the workspace exists, falling back to the original default
  Organization workspace when the header is absent — every Phase 1 API caller kept working
  unchanged.
- **Frontend**: `WorkspaceContext` fetches the workspace list once, persists the active selection
  in `localStorage`, and `api/client.ts` attaches `X-Workspace-Id` to every request from a
  module-level variable — no existing page's code had to change to become workspace-aware. Sidebar
  nav is now genuinely conditional: `AI Assistant` only appears when the Personal workspace is
  active, matching `IA.md`'s "which agents/pages appear depends on the active workspace" rule for
  real instead of just in the earlier IA-explorer mockup.
- **AI Assistant**: `POST /assistant/chat` grounds every answer in the active workspace's latest
  brief + findings only, with an explicit system-prompt instruction to say "I don't have that
  information yet" rather than invent an answer — this is the same anti-hallucination discipline
  the Engineering Agent uses (real evidence in, narrated out), applied to a conversational surface.
  Added `LLMClient.complete_text()` alongside the existing `complete_json()`, since forcing JSON
  mode on a human-facing chat reply would be wrong.
- **Verified workspace isolation for real, not just by code review:** asked the assistant the same
  question against the Organization workspace (which has a real brief) and the Personal workspace
  (empty) — got a correctly grounded answer citing the real finding for Org, and an honest "no data
  yet" for Personal. No data leaked across the boundary.
- **Real bug fixed along the way:** Alembic's autogenerate rendered the custom `UTCDateTime` type
  (added during Phase 1's timezone bugfix) as an unimported class reference
  (`app.models.base.UTCDateTime()`) the first time a *new* column used it — would have raised
  `NameError` on `alembic upgrade`. Fixed with a `render_item` hook in `alembic/env.py` so it always
  renders as the portable `sa.DateTime(timezone=True)` instead, for every future migration, not
  just this one.
- **Infra note:** at your request, local dev moved off Docker Compose entirely — backend, worker,
  beat, and the frontend dev server all run natively now (`.venv` + `npm run dev`) against your
  already-running local MySQL and Redis. `docker-compose.yml` is left in the repo as an alternative,
  not removed, in case it's useful again later (e.g. for a non-dev deployment).

### Known gaps (deliberately deferred, not oversights)

- **No real personal GitHub token tested** — same caveat as Phase 1's org connection; the smoke
  test reused Phase 1's seeded-signal approach rather than a live personal-account PAT.
- **Tasks/Calendar/Insights are not built** — as flagged when this phase was planned, these need
  Gmail/Calendar integration to mean anything; that's explicitly your next step after this.
- **Still no real login** — the "two workspaces for one implicit user" model is correct scaffolding
  for Phase 2's real accounts, but there's still no signup/session/password anywhere. Switching
  workspaces today is a UI preference, not an access-control boundary.
- **Assistant has no persisted chat history** — conversation lives only in frontend state; refreshing
  the page clears it. Fine for Phase 1.5, worth a `chat_messages` table if usage shows people want
  history back.

**Exit criteria:** a solo user (no team, no org) can connect their own GitHub account and receive a
personal daily brief through the same pipeline used in Phase 1. *(Structurally proven — Personal
workspace runs the identical pipeline as Organization — but not yet exercised with a real personal
GitHub account; the architecture is what was being validated here, and it held.)*

**⏸ Wait for signal before Phase 2.**

---

## Phase 2 — Team Workspace + Project Agent + RBAC

**Objective:** the first real demonstration of the core thesis — connecting dots *across* tools —
plus the first point where multiple users and roles actually exist.

**IA surface that goes live:** Team Workspace (`IA.md` §2.3); first real roles — Org Admin, Team
Manager, Employee (Guest and Super Admin still deferred).

| Step | Deliverable | Notes |
|---|---|---|
| 2.1 | Jira and/or Linear integration client | Sprint/board metadata: tickets, status, assignee, due dates |
| 2.2 | Project Agent | Sprint burndown reasoning, deadline-slip prediction |
| 2.3 | Executive Agent upgrade | Consumes multiple agents' findings; produces compound findings (engineering bottleneck + velocity drop → "Sprint at risk") |
| 2.4 | RBAC | Role column on `memberships`; permission checks per `IA.md` §3 matrix; Team Workspace pages (Dashboard, Members, Projects, Sprint Board, Reports) |
| 2.5 | Brief delivery beyond dashboard | Slack and/or email push of the daily brief |

**Exit criteria (from `ROADMAP.md`):** at least one compound finding a pilot user says they
wouldn't have caught themselves, surfaced at least a day before they would have caught it manually.

**⏸ Wait for signal before Phase 3.**

---

## Phase 3 — Communication + Knowledge + Organization Workspace

**IA surface that goes live:** Organization Workspace (`IA.md` §2.4) — Executive Dashboard,
Departments, Teams, Employees, Audit Logs.

| Step | Deliverable |
|---|---|
| 3.1 | Slack integration client |
| 3.2 | Communication Agent — gaps, unanswered questions, missing approvals |
| 3.3 | Notion/Confluence integration client |
| 3.4 | Knowledge Agent — stale/missing docs, duplication |
| 3.5 | Organization Workspace pages + org-wide Agent Center/Analytics roll-up |

**Exit criteria:** TBD once Phase 2 pilot feedback is in — noisier signal sources (Slack especially)
mean the precision bar from `PRD.md` §9 needs re-validating before shipping this phase.

**⏸ Wait for signal before Phase 4.**

---

## Phase 4 — Ops, Security, Finance, People

| Step | Deliverable |
|---|---|
| 4.1 | DevOps Agent — Docker/K8s/logs/deploy alerts |
| 4.2 | Security Agent — credential leaks, dangerous commits, secret exposure |
| 4.3 | Finance Agent — cloud cost spikes, API usage, budget overruns |
| 4.4 | HR Wellbeing Agent — **opt-in only**, team-level aggregate workload patterns, never individual judgment; requires its own privacy review before shipping |

Reprioritize within this phase based on pilot demand rather than the listed order — whichever
agent pilot users ask for first should jump the queue (per `ROADMAP.md`).

---

## Beyond Phase 4

- Guest role + "my one suggestion" surface
- Super Admin / platform administration tier
- Multi-tenant billing infrastructure
- GitHub App migration (from PAT) for scale and narrower permission scopes
- Autonomous *actions* (not just recommendations), gated per-action-type opt-in

---

## Open Questions to Resolve Before / During Phase 1.5

- **Tasks/Calendar/Insights in Personal Workspace** (§Phase 1.5): these imply Gmail/Google
  Calendar integrations not yet scoped anywhere in `ARCHITECTURE.md`. Recommend stubbing the pages
  but deferring real ingestion until a Personal-workspace pilot user actually asks for them —
  otherwise Phase 1.5 quietly grows a 4th and 5th integration before Phase 1's two agents have even
  been validated.
- **Guest's "My One Suggestion"**: intentionally the narrowest surface in the whole IA — worth
  confirming this stays a single AI-generated recommendation (no dashboard, no history) rather than
  scope-creeping into a lightweight version of the Employee view.
