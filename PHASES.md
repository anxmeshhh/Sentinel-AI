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

---

## Phase 1.6 — Auth Foundation ✅ Built and smoke-tested

**Objective:** replace `core/bootstrap.py`'s single implicit user with real accounts — the true
prerequisite named in `IA.md` v2 §8.2 for everything else in the Discord-style workspace model
(workspace creation, invites, roles are all meaningless without a real account to attach them to).

**IA surface this enables:** `IA.md` v2 §2.1's signup/login (Google, Microsoft, Email), still not
yet wired into workspace resolution or any existing route — see Known gaps.

| Step | Deliverable | Status |
|---|---|---|
| 1.6.1 | Password auth: signup, login, hashing | ✅ |
| 1.6.2 | OTP: email verification + passwordless login | ✅ |
| 1.6.3 | Google + Microsoft OAuth (conditionally active) | ✅ code complete, not yet exercised — needs real client id/secret in `.env` |
| 1.6.4 | Session JWT + `get_current_user` dependency | ✅ |

### What actually got built (technical notes)

- **`users` table extended**: `hashed_password` (nullable — OAuth-only users never set one),
  `email_verified`, `google_sub`/`microsoft_sub` (the provider's stable subject id, matched instead
  of email since email can change at the provider but the subject id never does).
- **New `otp_codes` table**: only the bcrypt hash of each code is stored, same discipline as
  passwords — a DB read never reveals a usable code. Capped attempts (`otp_max_attempts`) and a
  short expiry (`otp_expire_minutes`) bound brute-force guessing of a 6-digit code.
- **`core/email.py`**: a real `EmailSender` abstraction, not a stub — defaults to
  `ConsoleEmailSender` (logs the OTP instead of sending it), so signup/login work correctly with
  *zero* configuration. Verified for real: signed up, read the OTP out of `docker compose logs
  backend`, submitted it, got a valid session token back. Switching to real delivery later is
  `EMAIL_PROVIDER=smtp` + filling in `SMTP_*` in `.env` — no code changes.
- **OAuth (`core/oauth.py`)**: Google and Microsoft clients are only registered if their client
  id/secret are actually set — the app runs fine with neither configured, and hitting
  `/auth/{provider}/login` before then returns a clear 501 rather than crashing. Verified this
  graceful-absence path for real; the actual OAuth round-trip needs you to register an app in
  Google Cloud Console / Azure Portal and drop the client id/secret into `.env` (redirect URIs
  documented there) — that's the one piece only you can do.
- **Sessions are stateless JWT** (`core/auth.py`), sent as `Authorization: Bearer <token>`, not a
  cookie — consistent with the header-based pattern `X-Workspace-Id` already established, and
  simplest to test directly via curl/Swagger without CORS-credential complexity.
- **Deliberately not wired into any existing route yet.** `get_current_user` (`api/deps.py`) is a
  complete, working, standalone dependency — but `get_workspace_id` still resolves through the
  Phase 1 implicit-user bootstrap, unchanged. Rewiring every existing route to require real login
  is real work with real risk of breaking what's currently working; it's the explicit next step
  (`IA.md` v2 §8.2 point 4: role enforcement), not bundled into this pass.
- **Verified end-to-end for real, 11 separate HTTP checks**, not just unit tests: signup → OTP
  logged to console → wrong code rejected → correct code verified (flips `email_verified`, issues a
  token) → `/auth/me` authenticated → `/auth/me` with no token correctly 401s → password login →
  wrong password correctly 401s → duplicate signup correctly rejected → passwordless login-OTP
  request → both OAuth routes correctly 501 when unconfigured.

### Known gaps at the time (closed in Phase 1.7 below, right after)

- ~~Not wired into `get_workspace_id`~~, ~~no frontend login/signup pages~~ — both closed in Phase
  1.7.
- **OAuth round-trip still unexercised** — the code path is complete and the "not configured" path
  is verified, but nobody has actually clicked through a real Google/Microsoft consent screen
  against this code yet, since that needs your registered app credentials. Still open.

---

## Phase 1.7 — Auth Wired Into the App ✅ Built and smoke-tested

**Objective:** close Phase 1.6's two biggest gaps in the same session, at your request — a
standalone auth system nobody could actually use isn't worth much. Sign up → land in your own real
(empty) Personal workspace → use the whole app as yourself, for real.

| Step | Deliverable | Status |
|---|---|---|
| 1.7.1 | Auto-provision a Personal workspace per real user | ✅ |
| 1.7.2 | `get_workspace_id`/`GET /workspaces` require real auth + membership check | ✅ |
| 1.7.3 | Frontend `AuthContext`, Login/Signup/OAuth-callback pages | ✅ |
| 1.7.4 | Protected routes, `Authorization` header wiring, logout | ✅ |

### What actually got built (technical notes)

- **`core/bootstrap.py` rewritten, not extended** — the old anonymous-single-implicit-user
  functions (`get_or_create_default_workspace`, `get_or_create_default_user`,
  `get_or_create_personal_workspace`) are gone entirely, not left as dead code. The one function
  left, `provision_personal_workspace_for_user(session, user)`, is idempotent and keyed to a real
  `User` — called right after OTP-verified signup and on every OAuth login (safe either way, since
  it's a no-op after the first call).
- **`get_workspace_id` (`api/deps.py`) now requires `get_current_user`** — no anonymous fallback
  left. A `X-Workspace-Id` header is checked against the caller's actual `Membership` rows, not
  just "does this workspace id exist" — returns 404 (not 403) for a workspace that exists but isn't
  the caller's, so a valid-looking id can't be used to probe for other tenants' existence. No
  header defaults to the caller's own Personal workspace.
- **This is a real, verified breaking change, on purpose**: every route that used to work
  unauthenticated (briefs, connections, admin, assistant, workspaces) now 401s without a token.
  Confirmed directly rather than assumed.
- **Frontend**: `AuthContext` (JWT persisted in `localStorage`, loads `/auth/me` on mount),
  `WorkspaceProvider` now waits for `AuthContext` to resolve before fetching `/workspaces` (it
  needs a token to succeed) and clears its state on logout so a stale workspace list can never
  flash for the next account. `LoginPage` (password or OTP), `SignupPage` (signup → OTP-verify
  step), `OAuthCallbackPage` (reads the token from the URL fragment the backend redirects to),
  `App.tsx`'s `RequireAuth` wrapper redirects to `/login` when there's no valid session. Sidebar
  shows the logged-in user and a logout control.
- **Verified end-to-end with a brand-new real account, not the bootstrap one**: signed up
  `real-user@example.com` → read the OTP from `docker compose logs backend` → verified → got a
  session token → `/workspaces` returned exactly one fresh, uniquely-slugged Personal workspace →
  confirmed it's genuinely empty (`/briefs/latest` 404s honestly) → **confirmed cross-tenant
  isolation directly**: this new user's token against the *old* demo workspace's id correctly
  returns 404, not the old seeded data → created a real connection under the new account, listed
  it back, checked `/admin/stats` — all correctly scoped to the new user's own workspace.

### Known gaps (deliberately deferred, not oversights)

- **No role differentiation yet** — every membership is still created with the same role
  (`ORG_ADMIN`); "authenticated" and "authorized to do X specifically" aren't distinguished yet.
  That's Phase 2's RBAC-enforcement step, now that there's a real user to check a role *against*.
- **No workspace CRUD/invites yet** — a user can't create an "Acme Corporation"-style workspace or
  invite anyone into it; they only ever have their one auto-provisioned Personal workspace. Still
  Phase 2.
- **Old demo/seeded data is now permanently unreachable** — it belonged to the anonymous bootstrap
  account, which no real login can ever authenticate as. Not a bug — this *is* what real tenant
  isolation means — but worth knowing before wondering where a previous test brief went.
- **OAuth round-trip still unexercised** — same as above, needs your registered app credentials.

**⏸ Wait for signal before Phase 2.**

---

## Phase 2 — Workspace CRUD, Teams, Projects, RBAC Enforcement

**Objective:** the first real demonstration of the core thesis — connecting dots *across* tools —
plus the first point where multiple users, real workspaces (not bootstrap-seeded ones), and roles
actually exist and are actually enforced. Superseded from "Team Workspace" (v1 framing) to this by
`IA.md` v2 — Teams and Projects are now entities living inside a Workspace, not workspace kinds of
their own (`IA.md` v2 §8.1).

**IA surface that goes live:** `IA.md` v2 §2.2/§2.3 (create/join workspace, onboarding wizard),
§2.4 (Teams-are-channels join model), §3.4/§3.5 (Team page, Project page), and real enforcement of
the v2 §4 role set (Owner/Admin, Executive, Manager, Team Lead, Member, Guest — Super Admin still
reserved for the operator-only Admin panel per its existing note).

### Phase 2a — The Discord Core Loop ✅ Built and tested

Create a workspace → create a channel (Team) → invite someone → they join. This is the concrete,
sequenced slice that makes Sentinel actually feel like the Discord-style product it's meant to be.

| Step | Deliverable | Status |
|---|---|---|
| 2a.1 | `POST /workspaces` (create) | ✅ |
| 2a.2 | `Team` model + `TeamMembership` | ✅ |
| 2a.3 | `POST/GET /workspaces/{id}/teams` | ✅ |
| 2a.4 | `POST /teams/{id}/join`, `/leave` | ✅ |
| 2a.5 | `WorkspaceInvite` model | ✅ |
| 2a.6 | Invite create/preview/accept endpoints | ✅ |
| 2a.7 | Frontend: Create Workspace, channel rail, Create Team, Invite modal, Join page | ✅ |
| 2a.8 | Onboarding "Connect Integrations" (GitHub live, others coming-soon) | ✅ |

### What actually got built (technical notes)

- **`require_workspace_membership`** extracted as a shared auth primitive (`api/deps.py`) — both
  the header-based `get_workspace_id` (existing pages) and the new path-based Team/Invite routes
  use the same check, same 404-not-403 discipline (a workspace that exists but isn't yours doesn't
  confirm its existence).
- **Team creation auto-joins the creator** — you don't create a channel and then have to separately
  join it, matching how Discord actually behaves.
- **One invite model covers both scopes**: `WorkspaceInvite.team_id` nullable — a team invite
  literally *is* a workspace invite with that one field set, exactly as planned in `IA.md` v2 §2.4,
  not a second model.
- **Invite preview is deliberately public** (`GET /invites/{token}`, no auth) — you can see "X
  invited you to Acme Corporation / #Backend Team" before signing up, the way Discord shows a
  server preview pre-join. Accepting requires auth.
- **Frontend `next` redirect param** added to Login/Signup so the invite flow survives a
  login/signup round-trip: click an invite link while logged out → prompted to sign in or create an
  account → land back on the same invite → accept. `WorkspaceContext` gained a `refresh()` so a
  newly-joined workspace shows up immediately without a full page reload.
- **Verified the complete loop end-to-end with two real accounts**, not mocked: created "Acme
  Corporation," created "Backend Team" (creator auto-joined, `member_count=1`), generated both a
  workspace-level and a team-level invite, previewed the team invite unauthenticated, signed up a
  second real account, confirmed they started with only their own Personal workspace, accepted the
  invite, confirmed they now saw Acme Corporation *and* were a Backend Team member
  (`member_count` went 1→2), then had that second account freely create a third team ("Frontend
  Team") with zero invite needed (open-by-default), and confirmed the first account could see it
  unjoined (`is_member: false`) — every claim in `IA.md` v2 §2.4 checked against real behavior, not
  assumed from the code.
- Confirmed all of the above **survived a full container rebuild** — workspaces, teams, and
  memberships are all in MySQL, not in-memory state.

### Known gaps (deliberately deferred, not oversights)

- **No team-level roles** — `TeamMembership` is a plain join; access differentiation still only
  happens at the Workspace `Membership.role` level. Matches `IA.md` v2 §2.4's explicit MVP choice.
- **No invite revocation UI** — invites never expire/max-out unless you pass those fields via the
  API directly; the frontend's "Generate invite link" always creates an unlimited, non-expiring one.
- **No Team page content** — clicking into a channel today is just join/leave/invite in the rail;
  the actual Team page (Overview/Projects/Work/Members/Activity/Insights, `IA.md` v2 §3.4) needs
  Phase 2b's `Project` model and `team_id`-scoped Findings first.
- **Role enforcement still doesn't exist** — every Workspace member can create/invite/manage
  equally regardless of role. Phase 2b.2.

**Exit criteria:** you can create a second workspace from the UI, create a channel in it, generate
an invite link, and have a second account join it and see the channel — the full loop, no curl
required. **Met** — verified via the API directly; not yet click-tested in a real browser by you.

### Phase 2b — Everything else already scoped for Phase 2

| Step | Deliverable | Notes |
|---|---|---|
| 2b.1 | `Project` model | `Finding`/`Signal` gain optional `team_id`/`project_id` so Team/Project pages (`IA.md` v2 §3.4/§3.5) can show scoped Intelligence |
| 2b.2 | Role enforcement | Every route checks the requesting user's role via `get_current_user`, per `IA.md` v2 §4's permission matrix — the first point being a Workspace member means different things per role, not just "member or not" |
| 2b.3 | Jira and/or Linear integration client | Sprint/board metadata: tickets, status, assignee, due dates |
| 2b.4 | Project Agent | Sprint burndown reasoning, deadline-slip prediction |
| 2b.5 | Executive Agent upgrade | Consumes multiple agents' findings; produces compound findings (engineering bottleneck + velocity drop → "Sprint at risk") |
| 2b.6 | Brief delivery beyond dashboard | Slack and/or email push of the daily brief |

**Exit criteria (from `ROADMAP.md`):** at least one compound finding a pilot user says they
wouldn't have caught themselves, surfaced at least a day before they would have caught it manually
— now on a workspace the pilot user actually created and invited teammates into, not a seeded one.

### Phase 2c — Broaden Beyond Developers: Gmail + Calendar ✅ Built, ⏸ not yet click-tested

**Objective:** the pitch was never "engineering tool" — it's an operational layer for anyone in the
org. This phase makes onboarding's "Connect Integrations" step (2a.8) actually mean something for
a PM, an exec, or anyone whose work lives in email and meetings, not pull requests.

**Scoped down from the original plan, deliberately:** Google Meet doesn't need its own integration
— a Meet link is just a field on a Calendar event, confirmed once the Calendar client existed
(2c.4's "confirm this" resolved to "yes, no separate work needed"). Zoom stays deferred — separate
OAuth app, narrower audience, lower priority than getting Gmail/Calendar working first.

| Step | Deliverable | Status |
|---|---|---|
| 2c.1 | Google OAuth scope upgrade (data-connect flow, distinct from login) | ✅ |
| 2c.2 | Gmail client + signals | ✅ |
| 2c.3 | Google Calendar client + signals | ✅ |
| 2c.4 | Google Meet | ✅ — rides on Calendar, no separate integration needed |
| 2c.6 | Onboarding integrations step goes live for real | ✅ — Gmail/Calendar tiles now show real "Connect" buttons |

### What actually got built (technical notes)

- **A real technical problem, solved properly**: this app's auth is Bearer-JWT (not cookies), but
  connecting Google requires a full-page redirect to Google and back — and a browser navigation
  never sends custom headers, so the real session token can't make the trip. Fixed with the
  standard pattern: `core/auth.py` gained `create_connect_ticket`/`decode_connect_ticket` - an
  authenticated `POST /integrations/google/connect-ticket` (which *can* carry a real
  `Authorization` header) mints a short-lived (5 min), single-purpose ticket; that ticket, not the
  real session token, goes in the redirect URL. `decode_access_token` was hardened to explicitly
  reject anything carrying the ticket's `typ` claim, and verified directly both directions: a
  garbage ticket 400s, and — the more important check — a **real session JWT used as a connect
  ticket is also correctly rejected**, so a leaked ticket could never be upgraded into a full
  session even if it were somehow captured.
- **Two separate OAuth client registrations** (`core/oauth.py`): `google` (login, identity-only
  scopes, unchanged from Phase 1.6) and `google_data` (broader `calendar.readonly` +
  `gmail.readonly` scopes, `access_type=offline` for a refresh token). **Caught and fixed a real
  bug via testing, not assumption**: `access_type=offline` set in `client_kwargs` at registration
  time silently failed to reach the actual redirect URL (confirmed by inspecting the real
  `Location` header), while `prompt=consent` in the same dict *did* make it through — an
  inconsistency in what authlib forwards from registration-time config. Fixed by passing
  `access_type`/`prompt` explicitly at the `authorize_redirect()` call site instead, then
  re-verified the real header showed `access_type=offline` this time.
- **One OAuth consent, two Connections**: clicking "Connect" on either the Gmail or Calendar tile
  triggers the identical flow (both scopes requested together) — the callback creates *both* a
  `GOOGLE_CALENDAR` and a `GMAIL` `Connection` row from the one token response, so the user never
  has to click twice.
- **Token storage generalized**: `Connection.encrypted_token` used to always hold a single PAT
  string (GitHub). For Google it now holds an encrypted JSON blob
  (`{access_token, refresh_token, expires_at}`) — same Fernet layer, different plaintext shape,
  callers decide how to parse what's inside.
- **`Connection.org`/`repo` reused, not renamed** (avoided a risky migration touching Phase 1's
  working GitHub integration): for Google connections, `org` holds the connected Google account's
  email and `repo` holds a fixed label (`"calendar"`/`"gmail"`). `full_name` is now provider-aware.
- **Automatic token refresh** (`integrations/google_auth.py`): access tokens expire in ~1h;
  `get_valid_access_token()` checks expiry with a 5-minute buffer and refreshes using the stored
  refresh_token before every Calendar/Gmail ingestion run, persisting the new access token. A
  revoked/expired refresh_token raises a clear error rather than retrying forever.
- **Gmail's metadata discipline, actively enforced**: Gmail's API returns a `snippet` field (a body
  preview) even in `format=metadata` mode — `_normalize_message` deliberately never reads it, same
  pattern as the GitHub client discarding the `patch` field. Only Subject/From/To/Date headers are
  requested and stored.
- **`ingestion.py` refactored to dispatch by provider** rather than being GitHub-only — `Provider.GITHUB`/`GOOGLE_CALENDAR`/`GMAIL` each get their own handler function, sharing the same `SignalRepository.upsert()` idempotency guarantee Phase 1 established.

### Real bug found by your click-through (not caught by review or the API-level testing above)

**`Data truncated for column 'provider'` / MySQL `DataError` on the actual callback.** Root cause:
`connections.provider` and `signals.type` are native MySQL `ENUM` columns, and **Alembic's
autogenerate compares `sa.Enum` columns by name, not by member list** — adding
`GOOGLE_CALENDAR`/`GMAIL` to the `Provider` enum and `CALENDAR_EVENT`/`EMAIL` to `SignalType` in
the Python models produced a migration (`5e907f8f2c91`) with an **empty `upgrade()`** — autogenerate
saw nothing to change. The MySQL columns silently stayed at `enum('GITHUB')` and
`enum('PR','REVIEW_SUBMITTED','COMMIT','ISSUE')` the whole time; every test up to this point used
`GITHUB`/existing signal types, so nothing exercised the gap until a real `GOOGLE_CALENDAR` insert
hit the database for the first time — which only happens once you actually complete the Google
consent flow, i.e. exactly the step "verified via the API directly" couldn't reach.

Fixed with a hand-written migration (`a57135e90e41`) that explicitly widens both MySQL enums via
`op.alter_column`. Verified the fix directly (`SHOW COLUMNS` before/after) and confirmed the failed
insert correctly rolled back the whole transaction rather than leaving a half-written row.

**The general lesson, worth remembering for any future enum change**: adding a member to a Python
`enum.Enum` backing a MySQL-mapped `sa.Enum` column *always* needs a hand-checked migration —
autogenerate cannot be trusted for this specific case, confirmed twice now (this is the same class
of gap as the `UTCDateTime` custom-type rendering bug from Phase 1.5, just a different Alembic blind
spot). `git grep "sa.Enum"` across future migrations is worth a glance whenever a `*Type`/`*Status`/
`Provider`-style Python enum gains a new member.

### Known gaps (deliberately deferred, not oversights)

- **Zoom** — still fully deferred, not started.
- **No UI surfaces the ingested Gmail/Calendar signals yet** — Settings shows connection status, but
  the Personal Workspace's Tasks/Calendar/Insights pages (stubbed since Phase 1.5) still don't
  render this data. The Engineering/Executive agents also don't reason over these new signal types
  yet — ingestion exists, agent awareness of it doesn't.
- **No disconnect flow for Google connections** — `DELETE /connections/{id}` works (it's
  provider-agnostic), but there's no UI button for it on the Gmail/Calendar tiles yet, only on the
  GitHub repo list.

**Exit criteria:** a non-engineering pilot user (someone whose primary tools are email/calendar, not
GitHub) can connect at least one of these and get a finding that's actually about their work.
**Not yet met** — needs the real browser click-through first.

**⏸ Wait for signal before Phase 3.**

---

### Phase 2d — The Google Module: Mail & Calendar, Structured and Smart ✅ Built and tested end-to-end

**Objective:** Phase 2c got Gmail/Calendar ingesting; nothing surfaced it. This phase turns that
into an actually usable module — browsable, askable, and risk-aware — without turning into "10
different mixed items." Three deliberate constraints kept it tight:

1. **One data source of truth** — the existing `Signal` table. No new tables; Gmail's
   `payload.label_ids` (already captured since Phase 2c) is all that's needed to drive every
   grouping (starred/important/spam/category).
2. **One interaction model** — a small fixed set of structured filters (recent/starred/
   important/unread/spam/category/top), each a plain SQL query. The ask-bar is a rule-based
   phrase-matcher onto those same filters, not an LLM call — predictable, free, and fast.
3. **Security posture preserved, deliberately extended in one bounded way** — email bodies are
   never stored. When full content is actually needed (viewing an email, or a targeted Assistant
   question), it's fetched live from Gmail for that one message, used once, and discarded — a real
   DB compromise still can't leak the mailbox, which was the point of the original metadata-only
   rule.

| Step | Deliverable | Status |
|---|---|---|
| 2d.1 | Gmail spam/trash visibility fix (`includeSpamTrash=true` — was silently excluded) | ✅ |
| 2d.2 | Live, never-persisted body fetch (`GmailClient.fetch_message_body`) | ✅ |
| 2d.3 | Structured mail/calendar query service (`mail_query.py`, `calendar_query.py`) | ✅ |
| 2d.4 | `GET /mail`, `GET /mail/{id}/body`, `POST /mail/ask`, `GET /calendar` | ✅ |
| 2d.5 | Communication Agent — deterministic detection over email/calendar metadata | ✅ |
| 2d.6 | Assistant chat extended with mail/calendar context + on-demand body | ✅ |
| 2d.7 | Mail + Calendar pages, connected-sources status strip on the dashboard | ✅ |

### What actually got built (technical notes)

- **A real, previously-invisible bug found while scoping this**: Gmail's `messages.list` excludes
  `SPAM`/`TRASH` by default — every sync since Phase 2c had silently never seen spam mail at all.
  Fixed with `includeSpamTrash=true`; re-ingested and confirmed 3 previously-invisible spam messages
  became visible and filterable.
- **The live-fetch boundary is enforced at exactly three call sites, nowhere else**: the
  `/mail/{id}/body` endpoint (user opens an email), the Communication Agent's... actually *not* the
  agent — see below — and the Assistant's `_maybe_live_email_body` (a targeted content question).
  `GmailClient.fetch_message_body` parses the MIME tree for `text/plain` (falling back to
  HTML-stripped `text/html`, entities unescaped), caps output at `MAX_BODY_CHARS`, and is never
  called from anything that writes to the database.
- **The Communication Agent deliberately does NOT use live body fetch** — kept to the same
  deterministic-detection-from-stored-metadata discipline as the Engineering Agent (labels, subject
  lines, timestamps only). This was a scope trim to avoid changing `SpecialistAgent.analyze()`'s
  signature (session/token access) across every agent for one agent's benefit. Its three detectors,
  all real and tested against the live account: `stale_flagged_mail` (important/starred + unread,
  aging), `spam_surge` (recent vs. baseline spam rate), `calendar_overload` (daily meeting-hour
  totals + back-to-back count). First real run produced a genuine finding: *"86 important emails are
  over 20 days old, indicating a growing backlog of unattended messages"* (severity 0.70, confidence
  0.90) — deterministic candidate detection, LLM only narrated it.
- **Graph wiring: chained, not concurrently fanned-out.** `engineering -> communication ->
  executive` rather than a true parallel fan-out — sidesteps LangGraph's parallel-branch state-merge
  reducers entirely (a real class of bug) for a shape that's already effectively fan-in (multiple
  specialists, one synthesizer) without the concurrency risk. Each node only produces candidates for
  the signal types it understands, so it's a no-op (not an error) on a connection it doesn't apply
  to — confirmed both directions already worked before this phase (Engineering on a Gmail
  connection, now also Communication on a GitHub connection).
- **MySQL `JSON_CONTAINS` powers every label filter** — `payload.label_ids` is a JSON array;
  `SignalRepository._has_label()` wraps `func.json_contains(Signal.payload, json.dumps(label),
  "$.label_ids") == 1`. No schema change, no new columns.
- **The Assistant's targeted-content path is a bounded heuristic, not NLU**: a question only
  triggers a live body fetch if it (a) contains a content-intent word ("say", "about", "summarize",
  etc.) AND (b) keyword-overlap-matches a specific email's subject/sender with `find_best_matching_email`.
  Verified both branches: "what is the recent mail" answers from the structured summary alone; "what
  did the stipend email say" correctly matched and live-fetched that one email's real body.
- **Top 10 defined concretely**, not left ambiguous: important/starred first, topped up with plain
  recency if fewer than 10 flagged — implemented in `mail_query._list_top`.

### Known gaps (deliberately deferred, not oversights)

- **Confused naming, worth flagging for future-me**: `PHASES.md`'s own Phase 3 plan (3.2) already
  named a future "Communication Agent" for Slack gaps/unanswered questions. This phase's
  Communication Agent covers Gmail/Calendar instead, arrived earlier than planned, and is scoped
  differently (personal inbox/calendar risk, not team communication gaps). When Phase 3 happens,
  decide whether Slack detection extends this same agent or gets its own — don't silently conflate
  them.
- **Not yet click-tested in a real browser** — every layer (services, route handlers, full HTTP
  round-trip with real auth) was verified directly against the live `guptaanimesh020@gmail.com`
  account; the actual Mail/Calendar pages haven't been clicked through in a browser yet.
- **No caching on live body fetches** — opening the same email twice in a session re-fetches from
  Gmail both times. Deliberate for now (simplicity over a cache-invalidation problem for a feature
  this new), worth revisiting if it feels slow in practice.
- **GitHub OAuth connect flow** (browse + pick private repos, discussed alongside this phase) —
  explicitly parked by request, not started.

**Exit criteria:** ask "what's in starred" and get a real answer; open an email and see its real
content; get a real risk finding from actual mailbox/calendar data. **All three confirmed working
against the live account.**

---

### Phase 2e — Dashboard Redesign: Groups, Channels, Connections as one command center ✅ Built and tested

**Objective:** the connections hub (Phase 2d's card grid) started life on the Settings page, then
moved to the dashboard on its own. This phase gives it siblings: **My Groups** and **My Channels**,
so the dashboard becomes a genuine command center — every group you're in, every channel you've
joined across all of them, and every external connection, all one click away, without first
navigating into a specific workspace to see any of it.

| Step | Deliverable | Status |
|---|---|---|
| 2e.1 | `role` added to `GET /workspaces` (was fetched but never returned) | ✅ |
| 2e.2 | `GET /teams/mine` — every channel the user belongs to, across every workspace | ✅ |
| 2e.3 | My Groups card section — click switches the active workspace | ✅ |
| 2e.4 | My Channels card section + detail panel (member count, role, invite, leave) | ✅ |
| 2e.5 | Slack/Notion added as disabled "coming soon" cards alongside Zoom | ✅ |
| 2e.6 | Dashboard re-fetches its own data when the active workspace changes | ✅ |

### What actually got built (technical notes)

- **A real, previously-invisible bug fixed as a side effect**: `BriefPage` fetched connections/brief
  exactly once on mount (`useEffect(load, [])`) - switching the active workspace (from the sidebar,
  or now from a Group/Channel card) never re-fetched, so the dashboard silently kept showing the
  *previous* workspace's connections and brief after a switch. Fixed by re-running `load()` whenever
  `active?.id` changes - the click-to-switch UX this phase adds would have been visibly broken
  without this fix, which is how it got caught.
- **"My Channels" needed a genuinely new query shape**: every existing team endpoint is scoped to
  one workspace (`GET /workspaces/{id}/teams`), because until now nothing needed "all of a user's
  channels regardless of which workspace they're in." `GET /teams/mine` joins `TeamMembership ->
  Team -> Workspace -> Membership` (the last join pulls the user's *workspace-level* role, since
  `TeamMembership` itself carries no role of its own - access level has always come from the parent
  Workspace's `Membership.role`, per Phase 2a's design). Verified against real multi-workspace data:
  a second test account with real memberships in "Acme Corporation" returned both its channels with
  correct workspace names, member counts, and roles.
- **Channel detail panel scoped honestly, not aspirationally**: channels don't have a content
  feed yet (that's what a future "Project" entity would be - still unbuilt). Rather than fake a
  feed or silently do nothing, clicking a channel opens a real, useful panel with what actually
  exists today - member count, the user's role, invite, and leave - and switches workspace context
  so everything else on the dashboard (brief, connections) reflects that channel's workspace. This
  was an explicit scope call, not an oversight - see the "known gaps" note below.
- **Groups reuses `WorkspaceContext` directly** rather than fetching its own copy - `setActiveId` is
  the same function the sidebar's workspace switcher already calls, so a Group Card and the sidebar
  dropdown are just two entry points to the same state, never two sources of truth.

### Known gaps (deliberately deferred, not oversights)

- **No real "channel content" to show** - the detail panel is honest about this (member count, role,
  invite, leave), not a placeholder pretending there's more. A future Project/feed entity would give
  channels something to actually show beyond membership.
- **Not yet click-tested in a real browser** - every layer (new endpoints, role propagation, the
  `active?.id` re-fetch fix) was verified directly against real multi-workspace, multi-channel data
  via the API; the actual dashboard hasn't been clicked through in a browser yet.
- **Search/filter is a plain client-side substring match**, only shown once there are more than 3
  groups or channels - deliberately simple, no fuzzy matching or backend search endpoint.

**Exit criteria:** see every group and every channel you belong to as cards without navigating into
a workspace first; click a channel card and land in the right workspace with that channel's real
info. **Confirmed via direct API testing against a real multi-workspace account.**

---

### Phase 2f — AI Command: real tool-calling orchestration for the Google Connection Workspace ✅ Built, read-path tested end-to-end; write-path confirm-block verified, execution not yet run

**Objective:** every prior agent in this codebase follows one rule - "detection is deterministic
Python, the LLM only narrates a candidate that already exists." That rule is why findings are
trustworthy, but it also means nothing in Sentinel could actually *do* multi-step work across
services on request. This phase adds the one deliberate exception: a real tool-calling agent loop
that reads across Gmail + Calendar together, and - the first write capability anywhere in the
codebase - can create a calendar event, gated behind an explicit user confirmation step.

**Explicitly scoped to Google only for this pass** (per the user's own call when this was proposed):
the orchestration loop's mechanics aren't Google-specific (generic tool registry, generic
read/write split), but only Google tools are registered. GitHub/Slack/Zoom/Microsoft get the same
pattern when those providers themselves get built - not scaffolded empty ahead of time.

| Step | Deliverable | Status |
|---|---|---|
| 2f.1 | Verified Groq's `openai/gpt-oss-120b` supports real OpenAI-style tool calling | ✅ |
| 2f.2 | Calendar OAuth scope widened `calendar.readonly` → `calendar.events` (read+write on events only) | ✅ |
| 2f.3 | `GoogleCalendarClient.create_event()` - the first write call in the codebase | ✅ |
| 2f.4 | `services/orchestrator.py` - bounded tool-calling loop, read/write safety split | ✅ |
| 2f.5 | `POST /connections/google/command` + `/command/execute` | ✅ |
| 2f.6 | AI Command chat UI inside the Google Connection Workspace, plan/confirm/execute UI | ✅ |

### What actually got built (technical notes)

- **The safety model is the actual point of this feature, not a bolt-on**: read tools
  (`search_emails`, `read_email_body`, `list_calendar_events`) execute automatically inside the
  loop - they can't change anything. The moment the model calls the one write tool
  (`create_calendar_event`), the loop stops immediately and returns a plan instead of a result;
  nothing is touched until a *separate* confirmed request re-enters through
  `execute_planned_action()`, which re-derives the connection from `workspace_id` itself rather
  than trusting anything about the pending action's origin - a tampered confirm request still
  can't act outside the caller's own workspace.
- **Verified both halves for real, not just by reading the code**: a read-only multi-step command
  ("what are my top 3 most important unread emails, summarize them") produced a real two-tool chain
  - `search_emails` then `read_email_body` on a specific message - and a grounded summary quoting
  real content (a real coupon code, real instructions) from that email, not an invented one. A
  write command ("schedule a meeting tomorrow at 3pm... with a Meet link") correctly stopped at a
  plan (`{action: "Create Calendar Event", title: "Sprint Sync", start: ..., create_meet_link:
  true}`) and produced **no** calendar side effect, confirmed by never having called the execute
  step - the block works by construction, not by assumption.
- **New OAuth scope needs a real reconnect**: existing Google connections were authorized under the
  old `calendar.readonly` scope and can't create events with their current token.
  `google_data`'s scope is now `calendar.events` (covers both read and write on events, without the
  broader `calendar` scope's access to calendar settings/sharing) - taking effect requires clicking
  "Reconnect Google" once, which the existing `prompt=consent` flow already forces a real re-consent
  screen for.
- **`LLMClient` gained one new method**, `complete_with_tools()`, alongside the existing
  `complete_json`/`complete_text` - kept in the same single choke-point file per the project's
  standing rule that swapping LLM providers should stay a one-file change.
- **The one write path was deliberately never executed against the real account during this build**
  - the confirm-required block was verified by never calling the execute step, not by actually
  creating and then deleting a test event. Actually creating an event (even a harmless test one)
  needs the user to trigger it themselves through Reconnect Google + the real UI.
- **Two follow-up fixes, both caught from real usage screenshots, not review**: (1) the connection
  detail panel was an inline expansion below the dashboard's card grid, not its own page - moved to
  a dedicated `/connections/:provider` route (`ConnectionWorkspacePage`) so Google/GitHub/Zoom/Slack/
  Notion each get a real page with its own service-card grid, matching the same `ServiceCard` visual
  used on the dashboard (extracted into a shared component so both levels stay visually identical).
  (2) the model's replies defaulted to markdown pipe tables, which are unreadable in a narrow chat
  column - fixed two ways: the system prompt now explicitly asks for numbered/bulleted lists instead
  of tables, and a small dependency-free `Markdown` component renders bold/lists/paragraphs properly
  instead of dumping raw markdown syntax as plain text.

### Known gaps (deliberately deferred, not oversights)

- **Write execution not yet run against the real account** - needs the user to reconnect Google
  (new scope) and click "Confirm & Execute" themselves in a real browser.
- **Only one write tool exists** (`create_calendar_event`). No email-sending, no event
  editing/deletion, no Meet-only actions independent of Calendar.
- **No cross-provider orchestration yet** - GitHub, Slack, Zoom, Microsoft all still have zero AI
  Command capability, by design for this pass (see Objective above).
- **`MAX_STEPS = 5`** is an arbitrary bound, not tuned against real usage patterns yet.

**Exit criteria:** a natural-language command spanning Gmail + Calendar without the user picking
which service to use. **Read path confirmed end-to-end against real data; write path confirmed to
correctly refuse to execute without confirmation - actual execution needs the user's own
reconnect + click-through.**

---

### Phase 2g — AI Search, Loading UX, Mail Summarization & Calendar Views ✅ Built and tested end-to-end

**Objective:** Phase 2f proved the tool-calling loop works; this phase makes it actually good -
real search instead of a handful of fixed filters, real loading feedback instead of a frozen
button, structured email presentation instead of a raw paragraph dump, cached summaries instead of
re-paying LLM cost on every open, and a real visual Calendar instead of one list view.

| Step | Deliverable | Status |
|---|---|---|
| 2g.1 | Live whole-mailbox Gmail search (topic/sender/label/date), replacing the fixed-filter-only `search_emails` tool | ✅ |
| 2g.2 | `EmailSummary` cache table + `GET /mail/{id}/summary` (summary/key points/action items, generated once) | ✅ |
| 2g.3 | Mail page's expanded view: Subject/From/Date → AI Summary → Key Points → Action Items → collapsed Original | ✅ |
| 2g.4 | Calendar tools: explicit date ranges (`list_calendar_events`) + deterministic `find_free_slot` | ✅ |
| 2g.5 | Calendar Month grid view (Week/Day as filtered list views, Agenda unchanged) | ✅ |
| 2g.6 | Real SSE streaming for AI Command - live per-step status, not simulated | ✅ |

### What actually got built (technical notes)

- **Search moved from "filter the last 500 ingested messages" to "search the whole mailbox
  live."** The old `search_emails` tool only accepted a fixed filter enum (recent/starred/spam/
  top) over the locally-ingested Signal cache - "show my hackathon emails" had no way to work.
  `GmailClient.search()` now calls Gmail's own live query API; `mail_query.build_gmail_query()`
  translates structured tool arguments (keywords, sender, label_filter, since/until - extracted by
  the LLM from the request) into Gmail's native query syntax (`hackathon from:unstop is:important`).
  Verified against every example in the request: "show my hackathon emails" (keyword search, real
  results), "any important emails from Unstop" (sender + label combined), both doing genuine intent
  extraction into structured parameters before ever touching an API.
  **Side effect**: `read_email_body` no longer looks up a Signal row at all - it takes Gmail's
  native message id directly (now what `search_emails` returns as `id`), since live search results
  don't necessarily correspond to any locally-ingested row.
- **Summary caching is real, not just described**: `EmailSummary` (new table, keyed on
  `(workspace_id, message_id)`) stores the generated summary/key_points/action_items once.
  Measured directly: first open of a real email took 1.6s (live LLM call); the second open of the
  *same* email took 0.39s (cache hit, zero LLM cost) - confirmed the token-efficiency requirement
  actually holds, not just that the code looks like it should.
- **`find_free_slot` is deterministic, not the LLM guessing** - same discipline as every other
  agent in this codebase. It computes real gaps between existing events for a given day/hour-window/
  duration in plain Python; the LLM only narrates the result. Caught and fixed a real prompt
  ambiguity during testing: "find a free slot" was sometimes followed by the model proactively
  calling `create_calendar_event` unprompted - the write-confirmation gate still caught it correctly
  (nothing was created), but the system prompt was tightened so "find" doesn't imply "book."
- **Loading states are genuinely real, not simulated** - this was an explicit call before building:
  `run_command_stream()` is a generator yielding a status event the moment each step actually
  starts (`"Searching your emails…"` right when `search_emails` begins executing, not on a timer).
  `run_command()` (used by tests and the plain call path) now just drains the same generator, so
  there's exactly one loop implementation, not two. The streaming endpoint is POST, not GET, despite
  SSE convention - `EventSource` can't carry the `Authorization` header this app's auth requires, so
  the frontend reads the same `data: {...}\n\n` framing off a plain `fetch()` stream reader instead
  (`api.postStream` in `client.ts`). Verified the full real HTTP round-trip: real auth, real SSE
  frames, in the exact shape the frontend parses.
- **Calendar view scope, as agreed upfront**: Month is a real grid (event-count badges per day,
  click a day to open it). Week and Day reuse the existing Agenda list, just date-bounded to a
  7-day or 1-day window via a new `since`/`until` query on `GET /calendar` (and a dedicated
  `GET /calendar/month` for the grid) - not a full hour-by-hour time-grid renderer, which was
  explicitly scoped out as a second, separate UI investment.

### Known gaps (deliberately deferred, not oversights)

- **Mail page's structured summary view uses the same summary endpoint for every open** - there's
  no separate lightweight "just show me the raw text" fast path; opening an email always triggers
  (or reuses the cache for) a summary. Matches "prioritize summarized info by default" from the
  request, but means even a quick glance pays the summary-generation cost once.
- **Cross-service orchestration (Gmail → Calendar → Meet in one request) relies on the existing
  general-purpose tool loop, not new dedicated plumbing** - it wasn't separately built because the
  richer search + calendar tools from this phase already make it work through the same mechanism
  Phase 2f proved out. Not exhaustively tested against a real "email mentions an event, check my
  calendar" scenario end-to-end.
- **Week/Day calendar views are list-based, not a time grid** - deliberate scope trim, see above.
- **No Month-view click-through in a real browser yet** - verified at the API/service level only.

**Exit criteria:** natural search works without learning filter names; opening an email shows a
structured summary, not a wall of text; the same email never gets re-summarized; loading states
reflect real backend steps; Calendar has a real Month view. **All confirmed working against real
data - Month view and the full click-through UX not yet exercised in a live browser.**

---

### Phase 2h — Drive, Interactive Resource Links, Real Email Rendering, Split-Pane Reader ✅ Built and tested end-to-end

**Objective:** four related fixes/additions to the Google Connection Workspace, all from real usage
feedback (a real bad-rendering screenshot, not a hypothetical): add Drive as a fourth service, make
every resource Sentinel surfaces a real clickable link out to its actual platform (never rendered
inside Sentinel), fix HTML email parsing that was leaking raw CSS/entities into "Original Email",
and replace the dropdown-style email reader with a real split-pane list+reader.

| Step | Deliverable | Status |
|---|---|---|
| 2h.1 | Google Drive added as a fourth service (OAuth scope + Provider enum + `GoogleDriveClient`) | ✅ |
| 2h.2 | `search_drive` orchestrator tool + `GET /drive/search` for the new Drive page | ✅ |
| 2h.3 | Every AI Command reply uses real markdown links to the actual resource, never a bare name | ✅ |
| 2h.4 | HTML email parsing fixed: MIME-aware, deterministic, no LLM (`html2text`-based) | ✅ |
| 2h.5 | Mail page rebuilt as split-pane (list left, dedicated reader right) | ✅ |
| 2h.6 | Summarize is a separate, on-demand, collapsible action - original email is always the default | ✅ |
| 2h.7 | Calendar gained an inline "+ Schedule" area (manual form + the existing AI Command, reused) | ✅ |

### What actually got built (technical notes)

- **A real, previously-invisible bug found and fixed mid-build**: the very email used to test the
  HTML-parsing fix turned out to have a broken `text/plain` MIME part - a marketing template that
  literally dumped its raw, unstripped CSS into the "plain text alternative" instead of real plain
  text. The original priority ("prefer text/plain, it's already clean") was a bad assumption for
  real-world mail; flipped to prefer `text/html` (converted via `html2text` to markdown) whenever
  it exists, falling back to `text/plain` only when there's no HTML part at all. Verified against
  the actual email from the bug report: raw CSS and `&nbsp;` gone, real heading/bold/list/link
  markdown in their place.
- **HTML→markdown conversion is a deliberate choice, not incidental**: converting to markdown
  (rather than flattening to plain text, or rendering raw sanitized HTML) means the exact same
  `Markdown` component already built for AI Command replies renders email bodies too - one renderer,
  one set of link/bold/list/heading rules, used everywhere. `ignore_tables=True` was added after
  testing showed email-builder layout tables (used for visual structure, not real tabular data)
  otherwise leaked as messy `---|---` artifacts into the output.
- **Resource links are real, not decorative**: every tool result (`search_emails`,
  `list_calendar_events`, `search_drive`) now carries a genuine `url` field computed from real data
  (a Gmail deep-link, Calendar's `htmlLink`, Drive's `webViewLink`) - never invented. The system
  prompt requires the model to cite resources as real markdown links using those exact URLs. The
  `Markdown` component was extended to render `[text](url)` as a real external link
  (`target="_blank"`, `rel="noopener noreferrer"`). Verified: a real AI Command reply linked a real
  email via `https://mail.google.com/mail/u/0/#all/{message_id}`.
- **Mail's split-pane reader keeps thread-grouping**: clicking a multi-message thread opens a small
  date-chip picker inside the reader pane (not a second dropdown) to pick which message to read;
  clicking a single-message thread reads it directly - preserves the Gmail-style thread-count
  grouping built earlier without a second, conflicting expand/collapse interaction pattern.
- **Summarize is genuinely optional and cached**: opening an email calls `/mail/{id}/body` only
  (zero LLM tokens); a separate, explicit "Summarize ✨" click calls `/mail/{id}/summary`, which
  still reuses the `EmailSummary` cache built in Phase 2g - the original email is never replaced,
  the summary renders in its own collapsible section alongside it.
- **Manual event creation is a genuinely different code path from the AI Command's write tool** -
  `POST /calendar/events` executes immediately, no confirm-plan step, because a human filling out a
  form and clicking "Create" already *is* the confirmation; the plan-preview step exists
  specifically for actions an LLM inferred on its own, not ones typed by hand. The Calendar page's
  "Ask AI" tab reuses the existing `<GoogleAICommand />` component directly rather than duplicating
  its streaming/confirm/execute logic a second time.
- **Drive follows the exact same shape as everything else**: `drive.readonly` scope (least
  privilege, no write), metadata/link-only results (never file content), a `build_drive_query()`
  translating structured intent into Drive's native query syntax - the same pattern as
  `build_gmail_query()` from Phase 2g, reused deliberately rather than reinvented.

### Known gaps (deliberately deferred, not oversights)

- **Existing Google connections need one more "Reconnect Google" click** before Drive search or
  Calendar event creation will actually work - both need scopes (`drive.readonly`,
  `calendar.events`) that older connections don't have yet. Confirmed this gracefully degrades
  (the orchestrator returns a clear "Drive isn't connected" message rather than erroring) rather
  than failing silently.
- **No real write test was run against the live Calendar** - same restraint as Phase 2f: creating
  a real event (even a harmless test one) needs the user's own reconnect and their own deliberate
  click, not something to trigger unprompted on their real calendar.
- **Split-pane Mail reader and the Calendar Month view still haven't been through a real browser
  click-through** - verified at the API/service/type-check level, consistent with every other gap
  noted in this file that says the same thing.
- **Tracking-wrapped links inside HTML emails are left as-is** (e.g. an ESP's click-tracking
  redirect URL) rather than resolved to their final destination - that's what the sender actually
  embedded; rewriting it would be guessing, not fixing.

**Exit criteria:** every resource in an AI Command reply is a real clickable link, not a bare name;
opening an HTML email shows clean readable content instead of raw CSS; opening an email never
costs an LLM call, summarizing does and only on request; Drive is searchable the same way Gmail
and Calendar are. **All confirmed against real data except the two items above requiring the
user's own reconnect/click-through.**

---

### Bug fixes found via real usage, between phases

Two real bugs surfaced by the user actually using the app (not review), fixed the same day:

- **A link inside a real HTML email broke React Router navigation.** Root cause:
  `html2text`'s `protect_links=True` wraps urls as `[text](<url> "title")` to survive line-
  wrapping - dead weight since `body_width=0` already disables wrapping, and the Markdown
  component's link regex didn't understand that syntax, so the whole `<url> "title"` blob became
  a broken `href`. Fixed at the source (`protect_links=False`) and hardened the renderer as
  defense in depth: link urls are now cleaned and validated as real `http(s)` URLs before ever
  becoming clickable - anything else renders as plain text instead of a broken navigation.
- **A newly-created calendar event didn't appear anywhere in the app.** Root cause: scheduled
  ingestion only runs every `ingestion_poll_interval_seconds` (default 6h), so an event created via
  the manual form or the AI Command's confirmed write sat on the real Google Calendar but never
  reached the local Signal cache that Month/Week/Day/Agenda actually query - confirmed directly (2
  real events on Google's calendar, 0 in the local cache). Both create paths now call
  `ingest_connection()` immediately after creating an event.

---

### Phase 2i — Indian Calendar Intelligence, Meeting History ✅ Built and tested end-to-end

**Objective:** make Calendar India-aware (holidays/festivals, correctly categorized, with regional
filtering) and give the Meet Workspace a real Meeting History - both explicitly scoped to reuse
what Google's APIs actually make available, not invent data that doesn't exist.

| Step | Deliverable | Status |
|---|---|---|
| 2i.1 | Calendar client: preserve real `meet_url` (was discarded), sync cancelled events (were dropped), support querying any `calendar_id` | ✅ |
| 2i.2 | Indian holidays sourced live from Google's own public "Holidays in India" calendar - never hardcoded dates | ✅ |
| 2i.3 | Keyword-based category classification (National/Regional/Festival/Observance) calibrated against real data | ✅ |
| 2i.4 | `get_holidays` orchestrator tool for natural-language holiday questions | ✅ |
| 2i.5 | Holidays shown in Month/Agenda views, visually distinct from personal events, with category + state filters | ✅ |
| 2i.6 | Meet Workspace: dedicated Meeting History page (Upcoming/Past, search, both links external) | ✅ |

### What actually got built (technical notes)

- **Two real bugs found while building this, not before**: (1) reading Google's public holiday
  calendar 403'd with "insufficient scope" - `calendar.events` (added in Phase 2f) only covers the
  user's *own* event operations, not arbitrary `calendarId` lookups; needed `calendar.readonly`
  added alongside it (another "Reconnect Google" needed). (2) even after that, the request still
  403'd - the calendar id itself (`en.indian#holiday@group.v.calendar.google.com`) contains a `#`,
  which was being parsed as a URL fragment delimiter and silently truncating the request path to
  `/calendars/en.indian`. Fixed by `urllib.parse.quote()`-ing the calendar id before building the
  request path. Confirmed working only after both fixes landed together.
- **Dates are 100% dynamic, categories are a maintained keyword table - a deliberate, bounded
  exception to "never hardcode dates".** Verified against a full real year of data (2026): Diwali
  landed on the real 8 November 2026, Holi on the real 4 March - genuine lunar-calendar dates from
  Google, not computed or guessed. Only the *label* ("this is a Festival", "this is Regional to
  Kerala") comes from a static name-matching table, refined twice against real observed titles
  (Ramzan Id/Bakrid/Vaisakhi weren't initially recognized as festival/regional names, since Indian
  holiday calendars use colloquial names inconsistently) - genuinely different from hardcoding
  *when* a holiday falls.
- **Meeting History is honestly scoped to what's actually available.** Google's real Meet
  attendance/conference-record API (actual join times, actual attendees) is a Workspace-admin-only
  API - not available for a personal Google account, and this project has no Workspace admin
  access regardless. Meeting History is built entirely from the same Calendar Signal data Calendar
  itself already has: "duration" is the *scheduled* duration, "participants" are *invited*
  attendees, "status" (Upcoming/Past/Cancelled) is genuinely derivable (cancelled from Google's own
  `event.status`, upcoming/past from comparing scheduled time to now). The UI copy says this
  explicitly rather than implying real attendance data exists.
- **Cancelled events are now synced, not dropped.** `_normalize_event` used to skip any event with
  `status == "cancelled"` entirely, meaning a cancellation on Google's side never reached the local
  cache - a stale "still happening" row would sit there forever. Now cancelled events sync with
  their status intact, so the Agenda/Meeting History views show a real "Cancelled" badge instead of
  going silently stale.
- **Holidays are never stored locally** - queried live from Google every time (a year's worth of
  holiday data is small and cheap to fetch), consistent with "don't duplicate what the provider
  already serves." Same connection/token as the user's own Calendar - holidays aren't a separate
  service to connect, just a different `calendar_id` on the same API.
- **Verified end-to-end with real logic tests, not just code review**: inserted two local test
  Signal rows (never touching the real Google Calendar) to confirm `meeting_status()` correctly
  derives "upcoming" from a future scheduled time and "cancelled" from `event.status` overriding
  the time-based logic - then removed them. Real orchestrator queries ("When is Diwali this year?",
  "Show me the next three public holidays") confirmed against live Google data separately.

### Known gaps (deliberately deferred, not oversights)

- **Regional coverage is keyword-based, not authoritative** - Google's Indian holiday calendar
  isn't officially segmented by state, so "regional" classification and state tagging comes from a
  maintained table of well-known festival names, not a government source. Reasonable for major
  festivals (Onam/Pongal/Durga Puja/etc.), less complete for lesser-known state-specific observances.
- **Meeting History has no real attendance data** - see above, an honest API limitation, not a gap
  to fix later without a Workspace-tier Google account.
- **No click-through in a real browser yet** for the Month view's holiday indicators, the category
  filter chips, or the Meet Workspace page - verified at the API/service level, consistent with
  every other such note in this file.

**Exit criteria:** ask "when is Diwali" and get the real 2026 date; see holidays on the calendar
clearly separate from personal events, filterable by category and state; find upcoming/past
meetings with working external links to both the Calendar event and the Meet call. **All confirmed
against real data - full browser click-through still pending.**

---

### Phase 2j — Intelligent Drive & Organizational Memory ✅ Built and tested end-to-end (with real infrastructure limits documented, not hidden)

**Objective:** implement the user's "Intelligent Google Drive & Organizational Memory" spec -
natural-language Drive search, on-demand file understanding (never automatic), cross-document
search, document comparison, AI-powered meeting prep, smart resource recommendations, deadline
detection, and Drive analytics. Sections 11-13 of the spec (Cross-Service Universal Search across
GitHub/Jira/Slack/Notion, a dedicated semantic "Contextual Memory Search," Project-Based Knowledge)
were explicitly deferred - the user's own spec language frames them as "long-term goal" / "later
this architecture should extend to...", and building them literally now would mean standing up
connections and a vector-search layer that nothing in the product yet justifies. The existing
orchestrator's tool-calling loop already substantially achieves composite/cross-service search for
a single request without that infrastructure.

| Step | Deliverable | Status |
|---|---|---|
| 2j.1 | Live Drive file content fetch (`GoogleDriveClient.fetch_file_content`) - Docs/Slides/Sheets via export, PDF/.docx via download + text extraction, bounded and never persisted | ✅ |
| 2j.2 | `read_drive_file` + `list_meeting_history` orchestrator tools; system prompt taught composite workflow patterns (meeting prep, comparison, cross-document search, deadline extraction) | ✅ |
| 2j.3 | Drive Analytics (`GET /drive/analytics`) - real storage quota, type breakdown, largest files, all from live Drive API calls, no fabricated capabilities (no view counts, no access history - Drive's API doesn't expose those) | ✅ |
| 2j.4 | Drive page UI: collapsible analytics overview, per-file "Ask about this file" panel reusing `GoogleAICommand` via a new `contextPrefix` prop | ✅ |
| 2j.5 | Real composite-workflow verification: single-file summarize, cross-document search, document comparison, meeting prep - each run against the live connected account, not just code review | ✅ |

### What actually got built (technical notes)

- **Live-fetch-never-store discipline, same as Gmail bodies**: `fetch_file_content()` fetches on
  demand, capped, never written to any table. Google-native formats (Docs/Slides/Sheets) use
  Drive's `/export` endpoint; PDF and `.docx` are downloaded via `alt=media` and text-extracted
  with `pypdf`/`python-docx`; anything else returns a graceful "Sentinel can only read text-based
  files..." instead of erroring.
- **Composite workflows are not new endpoints** - meeting prep, comparison, cross-document search,
  and deadline extraction all emerge from the existing orchestrator tool-calling loop freely
  chaining `search_drive`/`read_drive_file`/`list_calendar_events`/`search_emails`/
  `list_meeting_history`, guided by system-prompt examples. Verified with real requests against the
  connected account: "compare my hackathon deck with my cover letter" produced an accurate,
  content-grounded comparison (correctly identified one as a competition pitch, the other as a job
  application, down to specific projects named in the cover letter); "prepare me for my next
  meeting" correctly chained calendar → email → Drive → meeting-history and produced a real prep
  checklist referencing the actual next event and an actually-relevant Drive file.
- **Four real, reproducible bugs found only by testing against the live account - not caught by
  code review or unit tests:**
  1. **gpt-oss-120b tool-name corruption**: the model's internal "harmony" format occasionally
     leaks channel/commentary tokens into a tool call's name (e.g.
     `search_drive<|channel|>commentary`), which Groq's API rejects outright. Fixed with a bounded
     retry in `complete_with_tools()` (temperature isn't 0, so a retry reliably produces a clean
     call).
  2. **`max_tokens` was never set on the tool-calling completion** - Groq's TPM accounting reserves
     room for the model's default completion length when it's left unset, and that reservation
     alone was consuming most of this account's 8000-tokens/minute on-demand-tier ceiling,
     independent of how small the actual prompt was (confirmed: a first-turn call with almost no
     conversation content still got rejected at "Requested 8442/8000"). Fixed by setting
     `max_tokens=3000` explicitly - enough headroom for the model's hidden reasoning tokens plus a
     real answer, without alone exhausting the per-minute budget.
  3. **A "no tool calls, but also no content" dead end**: with `max_tokens` too tight (1024, tried
     first), a multi-candidate search burned the whole completion budget on gpt-oss's hidden
     reasoning and returned truncated, empty final content - the user got a blank reply with no
     indication anything went wrong. Fixed two ways: raised the budget (see above) and added a
     hard floor in `run_command_stream()` that replaces any empty final reply with an explicit
     "I wasn't able to put together a clear answer" message - never ship silence to the user
     regardless of why the model produced it.
  4. **A composite request (meeting prep) could exhaust `MAX_STEPS` without ever answering** -
     confirmed real: the model repeatedly re-ran `search_emails` with only minor keyword/date
     variations instead of moving to synthesis, hitting the step ceiling with nothing to show.
     Fixed by raising `MAX_STEPS` 8→10 and adding explicit system-prompt guidance against redundant
     near-duplicate tool calls ("move to synthesizing an answer once you have 'enough', not
     'everything possible'"). Re-tested after the fix: the same "prepare me for my next meeting"
     request completed in 7 steps with a real, grounded prep checklist.
  5. Also caught while stress-testing: the model ignored the system prompt's "never use markdown
     tables" instruction once, on a comparison request. Reinforced the instruction to explicitly
     cover comparison-style answers ("use short bulleted 'A: ...' / 'B: ...' pairs... even for a
     'compare A vs B' answer").
- **Groq's rate limits are a real, external, two-layer constraint - documented honestly rather than
  papered over.** There's a per-minute ceiling (8000 TPM for this model/tier) and a separate daily
  ceiling (200,000 tokens/day). Both were hit for real during this session's testing: the per-minute
  one from a single composite request needing several tool round-trips in quick succession, the
  daily one from the cumulative volume of same-day live testing. Neither is fully solvable in
  application code on this account tier - both are now handled by *failing honestly* instead of
  crashing: a new `LLMOverloadedError` distinguishes non-retryable 413 (single request too large)
  and 429 (rate/quota exceeded) responses from the retryable gpt-oss formatting glitch, and the
  orchestrator surfaces its message directly to the user ("try narrowing it" / "hit its usage limit
  for now, try again shortly") instead of the generic connectivity-failure fallback or an unhandled
  500. This is a known, tracked platform constraint of the connected account's tier, not a bug to
  chase further without upgrading it.
- **`MAX_CONTENT_CHARS` for Drive file reads cut from 20,000 to 6,000 chars** - the old value alone
  (~5000 tokens) was consuming most of the 8000 TPM budget by itself before the `max_tokens` fix was
  even found, making any workflow needing more than one file read guaranteed to fail. Kept at the
  lower value even after the real fix landed, since it's still good token-efficiency practice for
  multi-file composite workflows (the user's own spec, §14, asks for exactly this).

### Known gaps (deliberately deferred, not oversights)

- **Sections 11-13 of the spec (Cross-Service Universal Search UI, a dedicated semantic
  "Contextual Memory Search," Project-Based Knowledge Graph) are not built** - the user's own spec
  language frames these as future direction, not a current ask, and they'd require unbuilt
  connections (GitHub/Jira/Slack/Notion inside this AI Command surface) plus a real vector/semantic
  search layer nothing in the product yet justifies.
- **Section 6 (dedicated "related file discovery" beyond what `search_drive` already returns) and
  section 8 (smart resource recommendations proactively surfaced on calendar events, rather than
  on-request) are not separately built** - reachable today by just asking the AI Command for them
  (which works, per the composite-workflow testing above), but there's no dedicated UI surface for
  either yet.
- **Cross-document search is real but rate-limit-fragile on the current Groq account tier** -
  confirmed working end-to-end (a real query correctly found and quoted a genuine mention in the
  hackathon deck), but a request needing several sequential searches/reads can occasionally collide
  with the account's per-minute or daily token ceiling, especially right after other heavy usage.
  When that happens it now fails with a clear, honest message rather than a crash - this is an
  external account-tier constraint, not something further code changes can fully eliminate.
- **No click-through in a real browser yet** for the Drive Overview analytics panel or the
  per-file "Ask about this file" toggle - verified at the API/orchestrator level against the live
  account, consistent with every other such note in this file.

**Exit criteria:** ask "summarize this file" / "which documents mention X" / "compare A with B" /
"prepare me for my next meeting" and get a real, content-grounded answer built from live Drive/
Gmail/Calendar/Meet data, not fabricated - confirmed against the actual connected account. **All
confirmed against real data - full browser click-through still pending.**

---

### Phase 2k — Channel Roles + RBAC Enforcement ✅ Built and tested (backend/API-verified; no new UI surface yet)

**Objective:** the first slice of the user's "Discord-Inspired Groups & Channels" spec. That spec's
Group/Channel hierarchy turned out to already be built and shipped (Phase 2a's `Workspace`=Group,
`Team`=Channel) - what's genuinely new is real role enforcement, which is also literally what this
whole Phase (Phase 2, title: "Workspace CRUD, Teams, Projects, RBAC Enforcement") always promised
and Phase 2b left scoped-but-unbuilt. Everything else in the new spec (per-channel Connections,
resource-level permissions, Channel AI, admin UI) is sequenced as 2l/2m/2n, confirmed with the user
up front as a phased build rather than one large unverified pass.

| Step | Deliverable | Status |
|---|---|---|
| 2k.1 | `ChannelRole` (channel_admin/channel_member) added to `TeamMembership`, `created_by_user_id` added to `Team` | ✅ |
| 2k.2 | Migration grandfathers every *existing* TeamMembership row to `channel_admin` - a data migration, not just a column default, so nobody loses access they already had | ✅ |
| 2k.3 | `require_workspace_role` / `require_channel_role` dependencies - real backend enforcement of the existing 5-role enum, which previously existed but was checked nowhere | ✅ |
| 2k.4 | Channel member management: list members + roles, promote/demote, remove - gated to Channel Admin (or a Workspace org_admin/super_admin, who can always manage any Channel) | ✅ |
| 2k.5 | Closed a real, previously-live privilege-escalation gap in invite creation | ✅ |

### What actually got built (technical notes)

- **A real security bug found while building this, not before**: `create_workspace_invite` and
  `create_team_invite` only ever checked that the caller was *some* member of the workspace
  (`require_workspace_membership`, existence only) - nothing stopped a plain `employee` or even a
  `guest` from minting an invite with `role: "org_admin"` or `"super_admin"` and handing it to
  anyone. Fixed by comparing the requested role's rank against the caller's own
  (`ROLE_RANK`, declaration order on the `Role` enum) and rejecting anything more privileged than
  the caller already holds - invite creation itself stays open to any member (preserves Phase 2a's
  tested Discord-style flow), only the *ceiling* on what role it can grant is now enforced.
- **Channel roles are independent of Workspace roles, on purpose.** A person can be Channel Admin
  of `#development` while a plain member of `#marketing` in the same Workspace - `TeamMembership`
  now carries its own `ChannelRole`, separate from `Membership.role`. A Workspace `org_admin`/
  `super_admin` can still always manage any Channel (Group Owner/Admin per the spec has full
  control) via `require_channel_role`'s bypass path, without needing an explicit `TeamMembership`
  row of their own.
- **The grandfather-clause migration matters more than it looks.** Every `TeamMembership` row that
  existed before this migration ran predates the concept of Channel roles entirely - under the old
  model every member could already do anything in their channel (no role existed to restrict
  them). Simply adding the column with a `channel_member` default would have silently *revoked*
  access nobody asked to have taken away. The migration's `UPDATE team_memberships SET role =
  'CHANNEL_ADMIN'` runs once, immediately after adding the column, and only touches rows that exist
  at that exact moment - anything created after (via join/invite/accept) already correctly defaults
  to `channel_member` in application code.
- **A real modeling bug caught before it shipped**: SQLAlchemy's `Enum` type stores a Python enum
  member's *name* in the DB column (`'CHANNEL_MEMBER'`), not its `.value`
  (`'channel_member'`) - confirmed by checking how the existing `membership_role`/`workspace_kind`
  columns were actually migrated. The first draft of this migration used `.value` as the column
  `server_default`, which would have been silently wrong (a value MySQL's ENUM type wouldn't even
  recognize) - caught by checking the established convention before applying it, not after.
- **Last-admin protection**: leaving, demoting, or removing the sole remaining Channel Admin of a
  channel that still has other members is rejected (`_reject_if_last_admin`) - a channel with
  members but no one able to manage its Connections/resources/roles going forward would be a real
  dead end. Leaving/removal is still allowed if it's the *last* member entirely - the channel just
  goes quiet, not un-manageable.
- **Verified against real data, not just the new unit test suite** (`tests/test_rbac.py`, 8 tests
  covering both the role-check dependencies and the invite escalation guard against a throwaway
  in-memory DB): also ran the migration against the actual connected account's real MySQL database
  and confirmed via live FastAPI `TestClient` calls (with a real JWT, real `Team`/`TeamMembership`
  rows) that `/teams/{id}/members`, `/teams/mine`, and `/workspaces/{id}/teams` all correctly
  serialize the new `channel_role`/`my_channel_role` fields, and that every pre-existing membership
  came back as `channel_admin` as intended - read-only checks only, to avoid mutating the real
  account's actual role assignments as a side effect of testing.

### Known gaps (deliberately deferred, not oversights)

- **No new frontend UI surface yet** - `channel_role`/`my_channel_role` fields are wired into the
  TypeScript types and API responses, but there's no visible "Promote to Admin" button or role
  badge anywhere yet. That's Phase 2n's job (dedicated admin management UI); building it before
  2l/2m (per-channel Connections, Channel AI) would mean designing it twice.
- **Workspace-level Owner vs. Admin is not split** - the spec's RBAC section describes a distinct
  "Group Owner" (full control) vs. "Group Admin" (channels/members/connections) tier; today's
  5-role enum only has a single `org_admin` top tier for a Workspace. Not introduced here to avoid
  a bigger, separately-risky schema change without a concrete need for it yet - noted for
  reconsideration once 2l/2n reveal whether the distinction is actually load-bearing.
- **`create_team`/`join_team`/`leave_team` still don't require any particular Workspace role** -
  any workspace member can still create or join a channel freely. This is Phase 2a's deliberate,
  already-tested open/Discord-style design, not something this phase changed; only the genuinely
  new admin-type actions (member role management, and anything 2l/2n add) are role-gated from the
  start.

**Exit criteria:** a Channel has its own Admin/Member distinction, independent of Workspace role; a
Guest can no longer mint an org_admin invite; every pre-existing member keeps the access they had
before this shipped. **Confirmed against real data at the API level - no browser click-through yet
since there's no new UI surface in this slice.**

---

### Phase 2l — Per-Channel Connections + Resource-Level Permissions ✅ Built and tested (backend/API only; no UI yet - that's 2n)

**Objective:** let a Workspace-level Connection be assigned to specific Channels, with allow-listing
on top for specific resources within it (a GitHub repo, a Drive folder, a Jira project) - spec
sections 4-6. `Connection` was 100% workspace-wide before this with zero per-channel scoping
concept anywhere in the schema.

| Step | Deliverable | Status |
|---|---|---|
| 2l.1 | `ChannelConnection` (team_id ↔ connection_id) + `ChannelConnectionResource` (allow-listed resource_key/label per assignment) models | ✅ |
| 2l.2 | `GET/POST/DELETE /teams/{id}/connections`, `POST/DELETE /teams/{id}/connections/{id}/resources` | ✅ |
| 2l.3 | `services/channel_connections.py`: `list_channel_connections`, `is_resource_allowed` - reusable by Phase 2m's Channel AI without importing route code | ✅ |

### What actually got built (technical notes)

- **Fail-closed by design, not fail-open** - this is the one part of the new spec's language that's
  unambiguous ("adding a Connection does not automatically give the Channel access to everything").
  Assigning a Connection to a Channel grants zero resource access on its own;
  `is_resource_allowed()` returns `False` unless a `ChannelConnectionResource` row explicitly
  allow-lists that exact `resource_key`. No separate "block" entry type exists - under
  default-deny, absence already means blocked, so a block row would add nothing. Verified with a
  real test (`test_assigning_connection_grants_no_resource_access_by_default`): assigning a real
  Connection and then immediately checking `is_resource_allowed` for its own resource key returns
  `False` until a resource row is added.
- **Workspace boundary enforced on assignment** - a Connection can only be assigned to a Channel
  within its own Workspace; attempting to assign a Connection belonging to a different Workspace
  404s (not 403, matching this codebase's "don't confirm existence of things outside the caller's
  scope" convention) rather than silently succeeding across a tenant boundary.
- **No credential exposure surface added** - `ChannelConnectionOut` only ever carries `provider` and
  `Connection.full_name` (the existing, already-safe display label); `encrypted_token` was never
  in scope for any new schema, matching the existing `ConnectionOut`'s convention.
- **Read access is for any Channel member, management is Channel-Admin-only** -
  `GET /teams/{id}/connections` passes both `ChannelRole` values to `require_channel_role` (i.e.
  "any actual member, or a Workspace admin via its existing bypass"), while assign/unassign/
  add-resource/remove-resource all pass admin-only. A plain Channel Member can see what's
  available to them but can't change it - verified in `test_plain_channel_member_can_view_
  assigned_connections` and `test_plain_member_cannot_remove_resource`.
- **A migration-discovery gap found and fixed while building this**: the new models were invisible
  to `alembic revision --autogenerate` at first - `alembic/env.py` maintains an explicit list of
  model modules to import so `Base.metadata` is fully populated before comparison, and the new
  `channel_connection` module wasn't in it. The first autogenerate attempt silently produced an
  empty migration (no error, just nothing to do) - caught by reading the generated file rather than
  assuming a clean run meant a correct one.
- **Verified with 7 real tests** (`tests/test_channel_connections.py`) against a throwaway in-memory
  DB, covering the fail-closed default, cross-workspace rejection, cascade delete of resources when
  an assignment is removed, and RBAC gating on every management action.

### Known gaps (deliberately deferred, not oversights)

- **No UI surface yet** - this phase is schema + API only, by design; Phase 2n is the dedicated
  admin management interface. Building it before Phase 2m (Channel AI) would mean designing the
  permission-management UI before knowing exactly what Channel AI actually needs to display.
- **Not yet wired into the AI orchestrator** - `is_resource_allowed`/`list_channel_connections`
  exist and are tested, but nothing calls them yet outside tests. That's Phase 2m's entire job:
  making the Channel AI actually respect these permissions when answering a request.
- **Only GitHub-shaped resources realistically usable today** - the model is provider-agnostic
  (`resource_key` is just a string), but only GitHub/Google Calendar/Gmail/Google Drive Connections
  exist at all in this codebase; Jira/Slack/Notion resource permissions from the spec's examples
  aren't meaningfully testable until those connections exist.

**Exit criteria:** a Channel Admin can assign a Workspace Connection to their Channel and allow-list
specific resources; a plain member can see what's assigned but not change it; nothing is
accessible until explicitly allowed. **Confirmed against real data via the unit test suite; no live
smoke test against a real Connection since no Connection exists in the specific Workspace tested
against - the underlying real account currently keeps its Connections in a Personal workspace with
no Channels of its own.**

---

### Phase 2m — Channel AI Workspace (Backend) ✅ Built and tested (orchestrator scoping only; no dedicated Channel page yet - that's still 2n)

**Objective:** make the existing AI Command orchestrator (Phase 2f onward) actually respect a
Channel's authorized Connections/resources instead of only ever operating workspace-wide - the
part of the spec that makes "enter your Channel, ask Sentinel, it knows what's authorized here"
real rather than aspirational.

| Step | Deliverable | Status |
|---|---|---|
| 2m.1 | `run_command`/`run_command_stream` gain an optional `team_id` - `None` (unchanged, still used by the plain Google AI Command) behaves exactly as before this phase | ✅ |
| 2m.2 | `_tool_schemas` filters which tools are even offered to the model, by which providers have a Connection actually assigned to the Channel | ✅ |
| 2m.3 | `_get_connection` - the second, real enforcement layer: even if tool-schema filtering were ever bypassed, a Channel-scoped tool call re-checks the Connection is genuinely assigned to that Channel, not just present in the Workspace | ✅ |
| 2m.4 | `read_drive_file` additionally checked against `is_resource_allowed` - the one tool with a natural per-item resource_key to allow-list against | ✅ |
| 2m.5 | `ChannelAIHistoryEntry` + `GET /teams/{id}/ai/history`; `POST /teams/{id}/ai/command`/`/stream`/`/execute` | ✅ |

### What actually got built (technical notes)

- **Fail-fast, not fail-silent, when a Channel has nothing assigned.** If `list_channel_connections`
  returns empty for a Channel, `run_command_stream` returns a clear "ask a Channel Admin to add a
  Connection" message *before* ever constructing an `LLMClient` call - confirmed by a real test
  (`test_channel_with_no_connections_assigned_never_reaches_the_llm`) that has zero Groq
  mock/network access at all and still passes, proving the short-circuit genuinely fires first.
- **Two independent enforcement layers, not one** - tool-schema filtering stops the model from even
  seeing an unavailable tool, and `_get_connection`'s Channel-assignment check re-verifies
  independently inside the tool executor itself. Belt-and-suspenders on purpose: schema filtering
  is a prompt-engineering-level control (a sufficiently determined or confused model could in
  theory still emit a call for a tool it wasn't offered), the executor-level check is the one that
  actually can't be talked around.
- **Resource-level enforcement is honestly scoped to Drive files only, not applied uniformly.**
  Gmail/Calendar-backed tools (`list_calendar_events`, `search_emails`, `list_meeting_history`,
  `get_holidays`) read from already-ingested, workspace-wide `Signal` rows with no per-item
  "resource" concept to allow-list against (unlike a Drive file or GitHub repo) - documented
  directly in `TOOL_PROVIDERS`' docstring rather than silently only-partially enforcing it. Those
  tools are still gated at the coarser connection-assignment level (unavailable entirely if
  Calendar/Gmail isn't assigned to the Channel), just not filterable to "only these specific events"
  the way Drive files can be filtered to "only these specific files."
- **The plain, non-Channel-scoped AI Command (`/connections/google/command/*`) is untouched
  behavior** - `team_id=None` takes every code path exactly as it did before this phase (same tool
  set, same connection lookup, no history logging). Confirmed both by 11 new unit tests and a real
  request against the live connected account ("what's my next upcoming calendar event?") returning
  a correct, unchanged answer after all the shared-code edits.
- **Verified with 11 real tests** (`tests/test_channel_ai_scoping.py`): tool-schema filtering in
  both directions (unfiltered when unscoped, filtered to exactly the assigned providers, empty when
  nothing's assigned), connection lookup honoring Channel assignment, Drive resource rejection and
  passthrough, the no-connections short-circuit, and history logging (including confirming the
  unscoped path logs nothing at all).

### Known gaps (deliberately deferred, not oversights)

- **No dedicated Channel workspace page yet** - this phase is the orchestrator/API layer only, on
  purpose (per the phased build the user confirmed): a Channel is still only a sidebar entry today,
  with no `/groups/:id/channels/:id` page showing the AI conversation + connections + members
  layout the spec describes. That's Phase 2n.
- **No proactive resource recommendations tied to calendar events** (spec section 8) - Channel AI
  answers on-request only, same pattern as the rest of this codebase's "ask, don't push" design.
- **Write actions (`create_calendar_event`) inherit the existing confirm-before-execute safety
  model unchanged** but aren't independently re-checked against Channel Connection assignment at
  the moment of `execute` - only at the moment the model proposed the plan. Low real risk (the tool
  couldn't have been offered in the first place without the Connection being assigned), noted for
  completeness rather than left unstated.

**Exit criteria:** a Channel with a Drive Connection assigned (and a specific file allow-listed) can
answer questions about that file; a Channel with nothing assigned gets a clear message instead of a
confusing failure; the original workspace-wide AI Command is provably unaffected. **Confirmed
against real data for the unscoped path; the Channel-scoped path confirmed via unit tests only, no
live Channel-with-a-real-Connection exists yet to test end-to-end against (same underlying reason
as Phase 2l - the connected account's Connections live in a Personal workspace with no Channels).**

---

### Phase 2n — Channel Workspace Page + Admin Management UI ✅ Built and tested (API-verified; browser click-through pending, consistent with every other UI phase)

**Objective:** give a Channel an actual place to live - until now everything from 2k-2m was
API-only and a Channel was still just a sidebar row. This phase adds the dedicated
`/channels/:teamId` page: Channel AI conversation front and center, with a collapsible context
panel (Connections / Members / Activity) implementing the spec's "Left = where am I, Center = what
am I doing, Right = what does Sentinel have access to here" principle.

| Step | Deliverable | Status |
|---|---|---|
| 2n.1 | `ChannelWorkspacePage` at `/channels/:teamId` - AI command area, assigned-connection chips, recent Channel AI activity | ✅ |
| 2n.2 | Context panel: Connections tab (assign/unassign, allow-list resources - admin-gated), Members tab (promote/demote/remove - admin-gated), Activity tab | ✅ |
| 2n.3 | `GoogleAICommand` gains `endpointBase`/`helpText` - Channel AI reuses the exact same streaming/confirm UI against `/teams/{id}/ai` | ✅ |
| 2n.4 | Sidebar channel names + dashboard Channel cards now navigate to the page; `GET /teams/{id}` single-lookup route for direct URL loads | ✅ |

### What actually got built (technical notes)

- **One AI Command component, two scopes.** Rather than a parallel Channel AI chat implementation,
  `GoogleAICommand` took an optional `endpointBase` (default unchanged, `/connections/google`) -
  the Channel page passes `/teams/{id}/ai`, and the entire streaming/status/confirm-execute flow
  works identically because the backend routes deliberately share the same event shapes.
- **Cross-workspace navigation handled explicitly**: a Channel is reachable from the "My Channels"
  dashboard card even when its parent Workspace isn't the active one - the page syncs the active
  workspace to the Channel's own `workspace_id` on load, so the global `X-Workspace-Id`-dependent
  calls (like listing assignable Connections) target the right Workspace instead of silently using
  whichever one happened to be active.
- **Admin actions are visibility-gated in the UI and enforcement-gated on the backend** - the
  panel hides Promote/Demote/Remove/Assign/allow-list controls from non-admins, but every one of
  those routes was already `require_channel_role`-gated in 2k/2l, so hiding is UX, not security.
- **A real bug caught before commit**: the members tab called `POST /teams/{id}/members/{uid}/role`
  but the backend route is `PATCH` - the api client simply had no `patch` method until now, and
  the mismatch would have 405'd on first real use. Caught by re-reading the route while writing
  the page against it.
- **Verified live against the real DB**: `GET /teams/{id}`, `/members`, `/connections`,
  `/ai/history` all exercised via TestClient with a real JWT against real rows (correct
  `my_channel_role: channel_admin` from the 2k grandfather migration, empty connections/history as
  expected for a never-used channel).

### Known gaps (deliberately deferred, not oversights)

- **No browser click-through yet** - same standing caveat as every UI phase in this file.
- **Channel AI history rendering is text-only** (line-clamped) - full Markdown rendering of past
  replies deferred until someone actually wants to re-read long answers from history.

**Exit criteria:** click a channel anywhere → land in its workspace page → ask Channel AI something
→ see it use only that channel's Connections; admins manage members/connections/resources in
place. **API layer fully verified; visual layer pending click-through.**

---

### Phase 2o — Manual Channel Creation & Management ✅ Built and tested end-to-end (full lifecycle verified live against the real DB)

**Objective:** the user's "Full Manual Channel Creation & Management System" spec - complete
manual ownership of channel architecture. Much of it already existed (member/connection/resource
management from 2k-2n); the genuinely new ground is channel metadata (description/icon/category),
privacy levels, archive/delete, category-grouped sidebar, the full creation modal, and - the
spec's one hard architecture rule - a single shared channel-management service that a future
AI-assisted creation flow must reuse ("Do NOT create separate Channel management logic for manual
and AI workflows").

| Step | Deliverable | Status |
|---|---|---|
| 2o.1 | `Team` gains description/icon/category/privacy/is_archived; migration defaults every existing channel to PUBLIC (exactly preserves their current open-join behavior - no grandfather UPDATE needed this time) | ✅ |
| 2o.2 | `services/channel_management.py`: create (full config: members, admins, connections), update, archive, delete-with-cascade, visibility filter - routes gate RBAC, the service validates config and writes | ✅ |
| 2o.3 | Privacy enforcement: PUBLIC = open join (unchanged); INVITE_ONLY = listed but join 403s (invite-accept is the entry path); PRIVATE = hidden from list AND direct lookup 404s for non-members (workspace admins excepted) | ✅ |
| 2o.4 | Channel creation now role-gated to super_admin/org_admin/team_manager (spec's explicit instruction - a deliberate behavior change from 2a's any-member creation) | ✅ |
| 2o.5 | Full Create Channel modal: icon/name/description/category, privacy radio, member picker (with per-member admin toggle; needs the new `GET /workspaces/{id}/members`), connection checkboxes; navigates into the new channel on create | ✅ |
| 2o.6 | Channel Settings (⚙ tab, admin-only): general fields, privacy, Danger Zone (archive/unarchive + permanent delete, both `confirm()`-gated) | ✅ |
| 2o.7 | Sidebar: channels grouped under category headers, channel icon shown, 🔒 on non-public, "invite only" replaces the Join button where joining isn't allowed, + Create Channel hidden from non-creator roles | ✅ |

### What actually got built (technical notes)

- **One service, two future entry points.** `create_channel()` takes the complete configuration
  (name/description/icon/category/privacy/members/admins/connections) and does all integrity
  validation itself: every member must already belong to the parent Workspace (a channel can't
  smuggle someone into a Group), every connection must belong to the Workspace (2l's tenant
  boundary, enforced at creation too), and the creator is always written as a Channel Admin - a
  channel can never be born without someone able to manage it, which is what makes 2k's
  last-admin rule sound from the very first row. When AI-assisted creation arrives, its tool call
  lands on this exact function.
- **Privacy semantics are deliberately asymmetric.** INVITE_ONLY stays *visible* (people should
  know the channel exists and ask for an invite) but self-join 403s; PRIVATE is a 404 on both the
  list and direct lookup for non-members - the same "don't confirm existence" convention as every
  other boundary in deps.py. The invite-accept path (which creates the TeamMembership itself) is
  untouched and is precisely how INVITE_ONLY/PRIVATE entry is supposed to work.
- **Archive is read-only, not gone**: hidden from every list (sidebar, My Channels), self-join
  blocked, Channel AI command routes 400 with an explicit "unarchive to use" message - but the
  page stays loadable by direct link (with a banner), history stays viewable, and settings stay
  reachable so an admin can unarchive. Delete is the hard path: explicit cascade over memberships,
  connection assignments (+ their allow-listed resources), AI history, and team-scoped invites -
  none of these tables have DB-level cascades (codebase convention), so the service deletes each
  explicitly, and a test proves the workspace Connection itself survives (it belongs to the
  Group; the channel only referenced it).
- **A real behavior change, called out rather than buried**: channel creation was any-member since
  Phase 2a; the spec explicitly restricts it to Group Owner/Admin, so it's now role-gated
  (team_manager included - managing team structure is that role's whole purpose) and the sidebar
  button hides for everyone else. Existing members with `employee` role lose the ability to
  create channels in workspaces they don't admin.
- **Verified twice over**: 9 new unit tests (`tests/test_channel_management.py` - full-config
  creation, outsider/foreign-connection rejection, role gating, all three privacy behaviors,
  archive exclusion, delete cascade) and a live TestClient lifecycle against the real MySQL DB
  acting as the real org_admin account: create → update → archive (AI 400s, hidden) → unarchive →
  delete → 404, self-cleaning with zero residual rows.

### Known gaps (deliberately deferred, not oversights)

- **Channel Types (General/Team/Project) not modeled** - the spec itself says not to overcomplicate
  if backend logic doesn't need them yet; `category` covers the visible grouping, and a `kind`
  column can be added additively when a type actually changes behavior.
- **Drag-and-drop reordering** - spec marks it optional; category grouping is alphabetical.
- **Resource selection at creation time** - the modal assigns Connections; allow-listing specific
  resources happens immediately after in the (already-built) channel panel, which the spec
  explicitly permits ("during Channel creation **or later through Channel Settings**").
- **AI-assisted creation itself** - future work by design; the service contract it needs is now
  the only creation path, so adding it is a tool schema + confirm flow, not new management logic.
- **No browser click-through yet** - same standing caveat as every UI phase.

**Exit criteria:** an authorized user manually creates a fully-configured channel (privacy,
members, admins, connections) from one modal and lands in it; admins edit everything later,
archive reversibly, delete permanently with confirmation; privacy is enforced by the backend, not
the UI. **Full lifecycle confirmed live against the real database.**

---

### Phase 2p — Attention Engine (backend) ✅ Built and tested end-to-end (real detection verified against the live workspace)

**Objective:** the first slice of the agreed next-phase strategy ("Sentinel tells you the five
things that matter today - and can prove why"). One new primitive - `AttentionItem` - unifying
everything actionable across sources (important emails, imminent meetings, stale PRs, agent
findings, manual reminders) into a single feed with a real lifecycle
(new/done/snoozed/dismissed). This is deliberately a *materialized* list, not a live query:
"done" and "dismissed" are user decisions that must survive every re-detection pass.

| Step | Deliverable | Status |
|---|---|---|
| 2p.1 | `AttentionItem` model + migration: type/origin/state, dedupe key unique per workspace, priority, due_at, snoozed_until | ✅ |
| 2p.2 | `services/attention_engine.py`: four deterministic detectors + idempotent reconcile (update in place / auto-resolve / never resurrect) | ✅ |
| 2p.3 | `/attention` API: list (with lazy snooze resurfacing), on-demand refresh, manual reminders, state transitions | ✅ |
| 2p.4 | Detection rides every sync cycle (guarded so a detection bug can never fail ingestion itself) | ✅ |

### What actually got built (technical notes)

- **Deterministic radar, AI brain - enforced, not just stated.** No LLM anywhere in detection or
  in the `why` lines, which are factual templates ("Starred, still unread — from Alice, 2d ago").
  This is simultaneously the precision play (never hallucinate an urgent thing), the
  rate-limit play (zero tokens per sync on the free Groq tier), and the trust play. The LLM
  budget is reserved for Phase 2q's Catch-Me-Up narration and on-demand investigation, where AI
  genuinely adds value.
- **Precision over recall, concretely**: emails require UNREAD + (STARRED, or IMPORTANT outside
  promotional/social categories - Gmail marks a lot of routine bulk mail IMPORTANT); meetings
  only within 24h and not cancelled; PRs only open >4 days; findings only severity ≥0.6 within
  3 days. Emails and PRs are capped at 5 each.
- **The dedupe key is the trust mechanism.** Same fact → same row, forever:
  `email:{id}`, `meeting:{id}:{date}` (each recurring occurrence gets its own row),
  `pr:{id}`, `finding:{id}`. Re-detection updates facts in place on NEW/SNOOZED rows only -
  DONE/DISMISSED rows are never touched again, so dismissing a noisy sender's mail is permanent.
- **Auto-resolution keeps the list honest**: a detected item whose underlying fact stops
  qualifying (email read in Gmail, meeting over, PR merged) auto-completes on the next refresh -
  the user never garbage-collects stale urgency. Verified by test: flipping an email's labels to
  read auto-completed its item.
- **Snooze needs no scheduler**: resurfacing happens lazily on read (snoozed_until elapsed →
  state flips back to NEW). Zero new infrastructure.
- **Verified against real data, not just the 11 unit tests**: live detection on the actual
  connected workspace produced 6 real items (1 communication-agent finding at 70% severity + 5
  genuinely-unread important emails, including a real domain-expiry warning), zero false
  meetings/PRs (correctly none in their windows). Live API lifecycle exercised end-to-end:
  list → done → snooze-validation 400 → manual reminder create → correct list membership.

### Known gaps (deliberately deferred, not oversights)

- **No UI yet** - Phase 2q is the dashboard strip + Attention hub + Catch Me Up.
- **Dismissals don't teach the detectors** (a dismissed sender's next email can re-qualify) -
  sender-level learning is logged as future tuning, after real usage shows which noise survives.
- **No deadline detector** - Drive deadline extraction is on-demand LLM work, not stored; wiring
  it in belongs with the "add to calendar" action flow (Phase E of the strategy).
- **Detection is workspace-scoped, not per-user** - correct for personal workspaces (one user);
  channel/team-scoped attention arrives with channel briefings (strategy Phase D).

**Exit criteria:** one API returns the ranked, deduplicated, lifecycle-aware list of what needs
attention across Gmail/Calendar/GitHub/agents; marking done sticks forever; re-syncs never
duplicate or resurrect. **All confirmed against the real connected workspace.**

---

### Phase 2q — Attention Dashboard + Catch Me Up ✅ Built and tested (Catch Me Up verified live with a real LLM narrative; UI click-through pending as usual)

**Objective:** make the Attention Engine the product's front door. The dashboard now leads with
the daily loop - "what changed while I was away" then "what needs me now" - and the full Attention
hub gets its own page.

| Step | Deliverable | Status |
|---|---|---|
| 2q.1 | `Membership.last_seen_at` + `GET /attention/catchup`: deterministic since-you-were-away diff (counts + real titles), LLM-narrated into ≤3 sentences with a deterministic fallback when the LLM is rate-limited/unavailable | ✅ |
| 2q.2 | Dashboard: `CatchMeUpCard` (only when away >12h, dismissible) + `AttentionStrip` (top 5, Done/Snooze/Open, optimistic with restore-on-failure) lead the page | ✅ |
| 2q.3 | `/attention` hub: state filters, ✨ AI-detected vs 📌 manual distinction, snooze menu (3h/tomorrow/next week), dismiss, reopen, manual reminder form with optional due date | ✅ |
| 2q.4 | "Ask Sentinel ✨" on any item → side panel reusing `GoogleAICommand` with the item as `contextPrefix` - investigation lands in the real orchestrator, zero new AI plumbing | ✅ |
| 2q.5 | "Attention" added to sidebar nav, directly under Dashboard | ✅ |

### What actually got built (technical notes)

- **The LLM is exactly where the strategy said it should be**: narrating Catch Me Up (one small
  `complete_json` call per genuinely-new visit) and investigating on demand. Verified live: with
  no prior `last_seen_at`, the real workspace produced a real 7-day narrative citing only real
  facts (176 emails, 89 important, the actual hackathon-kickoff/domain-expiry subjects, 1
  finding) - and the immediate second call correctly returned `narrative: None` (gap 0h), so the
  card never nags someone who was just here.
- **Rate-limit resilience by design**: `LLMError` → deterministic sentence built from the same
  facts. The feature degrades to "less charming", never to "broken" - a direct lesson from the
  Groq-tier incidents earlier in this project.
- **last-seen is per-membership, not per-user** - the same person can be away from one workspace
  while active daily in another; anchoring on `Membership` gets that for free.
- **Catch Me Up windows are capped at 7 days** so a month away produces a summary, not a novel.
- **Optimistic UI with honesty**: Done/Snooze remove the row instantly but restore it if the
  PATCH fails - never silently pretend an action stuck.

### Known gaps (deliberately deferred, not oversights)

- Strategy items not in this slice: channel briefings (Phase D), demo-workspace seed + persona
  onboarding (2r, expo insurance), deadline detection, dismissal-learning.
- Catch Me Up doesn't yet enumerate *changed* meetings (moved/cancelled) - only upcoming ones;
  needs event-revision tracking the Calendar sync doesn't store yet.
- No browser click-through yet - standing caveat.

**Exit criteria:** open Sentinel → see what changed and the ≤5 things that matter, each with a
factual why → act (done/snooze/dismiss/open/investigate) in place → tomorrow it's fresh again.
**Backend + live Catch Me Up verified against the real workspace; visual pass pending.**

---

### Phase 2r — Demo Workspace + Persona Onboarding ✅ Built and tested end-to-end (full "Prepare Me" flow verified live on seeded data)

**Objective:** two things that unblock everything else - let anyone experience Sentinel without
handing over OAuth to their real inbox, and make the "One Sentinel, different ways of working"
positioning concrete via a persona picker that *configures* one platform rather than forking it.

| Step | Deliverable | Status |
|---|---|---|
| 2r.1 | `User.persona` + `onboarded_at`; `Workspace.is_demo`; `SignalType.DRIVE_FILE` | ✅ |
| 2r.2 | `services/demo_data.py`: coherent cross-service scenario seeded as ordinary Signals, with relative timestamps | ✅ |
| 2r.3 | Orchestrator demo branches - Gmail/Drive tools read seeded Signals; real tool-calling loop otherwise untouched | ✅ |
| 2r.4 | `/onboarding` API (state, set persona, enter demo) + persona → suggested-connections mapping | ✅ |
| 2r.5 | Persona picker page + first-run gate + "Explore Sentinel" entry + demo banner on the dashboard | ✅ |

### What actually got built (technical notes)

- **The demo is real data through real code, not a puppet show.** Fake Gmail/Calendar/Drive/GitHub
  facts are written as ordinary `Signal` rows, and the *real* attention engine detects over them.
  Proven by what the demo correctly *ignores*: a planted read email, a planted promotional email,
  and a planted merged PR all fail detection exactly as they should. If a detector were wrong, the
  demo would show it being wrong - which is the point.
- **The AI genuinely reasons in demo mode.** Only the tool *implementations* change (Gmail/Drive
  read seeded Signals instead of calling a provider); the model runs its normal loop. Verified
  live with "Prepare me for my next meeting": it chained **7 tools** (`list_calendar_events` →
  `search_emails` → `list_meeting_history` → `search_drive` → `read_email_body` →
  `read_drive_file` ×2) and connected a client's contract question to the exact clause 7.2 text
  inside the proposal document. Nothing about that answer was scripted.
- **Relative timestamps are the difference between a live demo and a dead one.** Re-entering
  Explore re-seeds rather than duplicating, so the client meeting is always "in 3h" and the stale
  PR is always genuinely stale, whenever the demo is run - verified by a test asserting the
  meeting lands 2-4 hours out.
- **Demo mode cannot perform real external writes.** `execute_planned_action` refuses in a demo
  workspace with an explicit message. The propose-and-confirm flow still renders fully (so the
  safety model is demonstrable) - only the actual write is refused, rather than silently
  pretending an event was created somewhere.
- **A migration gap worth recording**: alembic's autogenerate detects new *columns* but not a new
  *value* added to an existing enum, and MySQL stores an ENUM's allowed values in the column
  definition. `DRIVE_FILE` therefore needed an explicit `ALTER TABLE signals MODIFY COLUMN` (with
  the full value list, since MySQL replaces rather than appends) - without it every insert of the
  new type would fail at runtime with a truncation error, and the autogenerated migration gave no
  hint anything was missing.
- **Persona is configuration, never a fork** - it only orders which connections we suggest first
  and which surfaces get emphasis. Nothing is permanently hidden, and persona is changeable at any
  time. Kept on `User` (not Workspace) because "how I work" is a property of the person.
- **Verified with 10 new tests + a live API pass** covering seeding, real-detection-not-scripted,
  re-seed idempotency, relative timestamps, credential-free tool reads, cross-workspace scoping
  (demo tools can't leak into another workspace), write refusal, and inertness for real workspaces.

### Known gaps (deliberately deferred, not oversights)

- **The "2-3 follow-up questions" from the strategy aren't built** - persona alone drives
  suggestions today. Worth adding only once there's evidence the extra questions change anything
  materially; a longer form on first run is a real cost.
- **Demo GitHub/Drive are seeded, not interactive** - you can read demo documents but not edit
  them, and external "Open in ..." links point at placeholder URLs (clearly demo data, not
  pretending to be real resources).
- **`get_holidays` is disabled in demo** rather than faked - inventing public holiday dates is
  exactly the kind of fabricated fact this codebase refuses to produce.
- **No profession-specific demo variants yet** (student/sales/admin) - the current scenario
  deliberately covers both launch audiences (startup/developer *and* busy professional) in one
  dataset; more variants belong with the connections that would back them.

**Exit criteria:** a visitor with no accounts picks "Explore Sentinel", lands in a workspace with
real-looking work already in it, sees a genuinely-detected attention list, and can ask "prepare me
for my next meeting" to watch Sentinel reason across mail, calendar and documents at once.
**Confirmed end-to-end, including the full 7-tool AI investigation.**

---

### Phase 2s — Channel Briefings ✅ Built and tested (scoping verified live, widening and excluding correctly)

**Objective:** extend the attention loop into Channels - "what needs this channel's attention" -
scoped strictly to the Connections and resources that channel is actually authorized for. Reuses
the Phase 2p engine entirely; no new detection.

| Step | Deliverable | Status |
|---|---|---|
| 2s.1 | `services/channel_briefing.py`: channel scope resolution + per-item visibility rules | ✅ |
| 2s.2 | `GET /teams/{id}/briefing` (any channel member) + `channel_pending_count` for header chips | ✅ |
| 2s.3 | LLM narrative with deterministic fallback, same discipline as Catch Me Up | ✅ |
| 2s.4 | Briefing card on the channel page, above the AI box | ✅ |

### What actually got built (technical notes)

- **Enforcement happens at selection time, never by hiding in the UI.** An item is only visible if
  a Connection for its source provider is assigned to that Channel. Verified live: a channel with
  only GitHub assigned showed exactly its 2 stale PRs; adding Gmail widened it to 5; and the
  upcoming meeting stayed **excluded throughout** because Calendar was never assigned.
- **Findings are attributed through their agent run's connection**, not assumed workspace-wide -
  a finding about the GitHub connection stays invisible in a channel that only has Gmail. This
  needed a join (`Finding → AgentRun.connection_id`) rather than a provider guess.
- **Personal manual reminders never leak into a channel.** They belong to whoever created them; a
  shared team view is the wrong place for "call the dentist".
- **A deliberate, documented asymmetry in resource scoping.** Drive-backed items are fail-closed
  (hidden until a document is explicitly allow-listed). Email/calendar/PR items are
  connection-gated only - not as a shortcut, but because their Connections are already 1:1 with
  their scope here (a GitHub Connection *is* one repo; a Gmail Connection *is* one mailbox), and
  an email that hasn't arrived yet cannot be pre-allow-listed by an admin. This mirrors the
  orchestrator's existing split exactly, where `search_emails`/`search_drive` are
  connection-gated and only *reading a specific document* is resource-gated. The reasoning is
  written into the module docstring so the next person doesn't "fix" it into something that makes
  email briefings structurally impossible.
- **Briefings are read-only, on purpose.** Done/snooze/dismiss stay in the personal Attention hub,
  because an item's lifecycle belongs to the person acting on it - one member marking something
  done shouldn't silently clear it from a teammate's view. A shared lifecycle deserves a real
  decision, not a default that falls out of implementation convenience.
- **`channel_pending_count` never narrates**, so a header chip can't quietly spend an LLM call on
  every channel page load - proven by a test that would fail if it tried.
- **9 new tests, mostly about what a channel must NOT see**: unassigned connections, another
  connection's findings, personal reminders, un-allow-listed documents, resolved items, and
  cross-channel isolation.

### Known gaps (deliberately deferred, not oversights)

- **No channel-level "since you were last here"** - the briefing is current-state only. Per-member
  per-channel last-seen is the same shape as `Membership.last_seen_at`, worth adding when someone
  actually asks for it.
- **No pending-count chip in the sidebar channel rail yet** - the count helper exists and is
  tested; wiring it into the rail means a fan-out query per channel, which needs a batched
  endpoint first rather than N requests.

**Exit criteria:** a channel with connections assigned shows exactly the attention items those
connections authorize, narrated in a sentence or two, and shows nothing at all when nothing is
assigned. **Confirmed live, including correct exclusion of an unassigned source.**

---

### Phase 2t — Deadline Detection + Add to Calendar ✅ Built and tested (real deadline found in the live inbox; full propose-confirm flow verified)

**Objective:** turn dated commitments buried in subjects and documents into first-class attention
items, and let the user put any of them on their real calendar through the existing
confirm-before-write flow.

| Step | Deliverable | Status |
|---|---|---|
| 2t.1 | `services/deadline_parser.py`: keyword-gated, deterministic date extraction (ISO, written months, relative, weekday, tomorrow/today) | ✅ |
| 2t.2 | `AttentionType.DEADLINE` + detector over email subjects and document text, priority scaled by urgency | ✅ |
| 2t.3 | Duplicate suppression - one underlying fact yields exactly one item | ✅ |
| 2t.4 | `POST /attention/{id}/calendar-plan` → propose; existing execute endpoint → write | ✅ |
| 2t.5 | "Add to Calendar" button + confirmation panel on the Attention hub | ✅ |

### What actually got built (technical notes)

- **A date alone is never a deadline.** The rule doing the real work is that a deadline *keyword*
  must be present: "Sprint planning on Friday" is not a commitment, "Respond by Friday" is. This
  keeps the parser silent across the enormous volume of ordinary dated text. Verified against the
  live inbox: it correctly found "IPO closing today" (keyword + resolvable date) while correctly
  *rejecting* "You have domain(s) expiring soon" - keyword present, but "soon" is not a date.
- **No LLM anywhere in detection**, for three converging reasons: a hallucinated deadline sends
  someone chasing a commitment that doesn't exist; this runs over every subject on every sync and
  would exhaust the free-tier budget; and patterns are auditable in a way a model's guess isn't.
- **Ambiguous numeric dates are deliberately unsupported.** `11/12` is 11 December or November 12
  depending on the writer's locale, and guessing produces a *confidently wrong* deadline - the
  exact failure this module exists to prevent. Covered by a test asserting silence.
- **Duplicate suppression was a real bug caught by looking at output, not by a test.** An email
  like "Invoice INV-2291 is due in 3 days" legitimately trips two detectors, and the first live run
  showed it listed twice - precisely the noise that makes an attention list feel untrustworthy.
  The deadline (which carries the date and the higher priority) now wins and the plain email item
  is dropped, before anything is written.
- **What's detectable is bounded by what's stored, honestly.** Email *bodies* are never stored (a
  deliberate privacy property since Phase 2c), so subject lines are the real surface. Document
  text is scanned only where it already exists rather than re-downloading every file each sync;
  deadline extraction from live Drive documents remains an on-demand AI action.
- **Add to Calendar reuses the one confirm-before-write path.** `calendar-plan` is deterministic
  and writes nothing - title and time come straight from the item, so what the user confirms is
  exactly what they already saw. The write goes through the same execute endpoint every other
  external action uses, so the demo workspace's refusal applies here too (verified: 400 with an
  explicit message, rather than pretending).
- **A channel-scoping refactor fell out of this.** Deadlines can originate from Gmail *or* Drive,
  which broke the assumption that an item's type implies its provider. Channel visibility now keys
  off each item's own `source_provider`, so an email-sourced deadline is connection-gated while a
  document-sourced one is resource-gated - matching the rule already documented in Phase 2s
  instead of quietly contradicting it.
- **17 new tests** (13 parser boundary cases, 4 detector/suppression), most asserting what must
  *not* be detected.

### Known gaps (deliberately deferred, not oversights)

- **Precision needs real-usage tuning.** The live run surfaced "IPO closing today" from a
  promotional mail - technically a correct parse, but arguably not the user's commitment. Sender
  reputation or category weighting is the obvious lever, and it should be driven by which items
  people actually dismiss, not guessed at now.
- **No recurring-deadline understanding** ("due every Friday") - single dates only.
- **Periods aren't parsed** ("by end of quarter", "before the holidays") - deliberately, since
  resolving them requires assumptions about someone's fiscal calendar.
- **Add to Calendar creates a 30-minute block** at the deadline time; it doesn't try to infer how
  long the work takes, because it has no basis to.

**Exit criteria:** a dated commitment in an email subject or document becomes a ranked attention
item with its due date, appears once and only once, and can be put on the real calendar in two
clicks with an explicit confirmation. **Confirmed against real inbox data and end-to-end through
the propose-confirm flow.**

---

### Phase 2u — "Prepare Me": structured meeting briefs ✅ Built and tested (10× cheaper than the orchestrator path, verified on real and demo data)

**Objective:** the first Goal-Based Intelligence workflow. The user asked for a "Goal Engine"
(intent → connections → permissions → retrieval → synthesis); analysis showed **6.5 of those 8
steps already existed** in the orchestrator, which had already produced good meeting briefs twice
in testing. So this phase deliberately did *not* build a goal engine.

**What was actually missing** was (a) discoverability - the capability was reachable only by
typing the right sentence into a text box, and (b) cost - the orchestrator path takes ~7
sequential LLM round-trips, which against this project's real 200k/day ceiling is roughly seven
briefs per day.

| Step | Deliverable | Status |
|---|---|---|
| 2u.1 | `services/meeting_prep.py`: deterministic progressive retrieval + one synthesis call | ✅ |
| 2u.2 | `MeetingBrief` cache table (EmailSummary's precedent) | ✅ |
| 2u.3 | `POST /attention/{id}/prepare` and `POST /meetings/{id}/prepare` - two entry points, one implementation | ✅ |
| 2u.4 | `Prepare Me ✨` button on meeting attention items and upcoming meetings on the Meet page | ✅ |

### What actually got built (technical notes)

- **The core decision: for a known goal shape, don't make the LLM plan - make it synthesize.**
  Meeting prep has a fixed shape (the meeting → attendee emails → title-matched documents → prior
  meetings), so retrieval is deterministic Python and the LLM is called **once**. Measured on the
  same demo meeting the orchestrator handled earlier: **1.7s and 1 LLM call** versus ~7 calls,
  producing a brief of comparable quality (it found the same clause-7.2 contract question, the
  proposal, and the demo script). Cached re-open: **0.002s, zero tokens.**
- **This is the codebase's own pattern, not a new one** ("detection is deterministic, the LLM
  narrates"). The orchestrator remains the deliberate exception for open-ended questions - it is
  explicitly *not* replaced. Two retrieval strategies, one intelligence architecture; no fifth
  chatbot.
- **Progressive retrieval is enforced in code, not suggested in a prompt.** No attendees → the
  email and prior-meeting searches never run. Generic title ("Meeting", "Sync", "1:1") → Drive is
  never queried, because searching for "Sync" returns noise the user pays for in tokens. Nothing
  found → the LLM call is skipped entirely and an honest "nothing to review" message is returned,
  since filler that reads like insight is worse than an honest blank. **Proved on real data**: a
  generic-titled solo meeting produced its brief in **0.01s with zero API and zero LLM calls.**
- **Attendee-based email search, not keyword guessing.** Searching Gmail for the attendees' real
  addresses is both more precise and closer to what a person actually does before a meeting than
  searching for words from the title.
- **Two real bugs caught by running it, not by tests.** (1) `structlog` reserves `event` as its
  own parameter name, so passing `event=` as a log kwarg raised at runtime. (2) A blanket
  `len(word) > 2` keyword filter silently discarded exactly the short tokens that carry the most
  meaning in work titles - `Q3`, `AI`, `UX`, `v2` - while a bare `1` from tokenizing "1:1" slipped
  through. The rule now keeps long words, digit-bearing tokens and all-caps acronyms, and drops
  short bare numbers.
- **Permissions are reused, not reimplemented**: retrieval goes through the orchestrator's
  existing `_get_connection`, so a brief requested inside a Channel can only read that Channel's
  authorized connections.
- **Every claim is traceable.** The brief lists each source (meeting, email, document, prior
  meeting) with a link out, so the user can verify rather than trust.
- **13 new tests**, focused on the cost controls and honesty guarantees: skip rules actually skip,
  an empty result spends no LLM call (proved by the test having no Groq access at all), briefs
  cache and rebuild in place, and prior-meeting matching excludes future events.

### What was deliberately NOT built (and why)

- **A generic goal parser / intent classifier** - the orchestrator already is one.
- **A multi-goal workflow registry** - premature abstraction at N=1. If a second structured
  workflow earns its place, the shape can be extracted then, from two real examples.
- **"What's happening with Project X?"** - needs Jira and project↔channel linkage that doesn't
  exist yet.
- **An autonomous next-action engine** - the brief states concrete prep points as text; acting on
  them stays the user's decision, and the one existing write path is already confirm-gated.
- **"Help me understand this item"** - already shipped as "Ask Sentinel ✨" in Phase 2q.

### Known gaps (deliberately deferred, not oversights)

- **The cache never self-invalidates.** If the meeting or its context changes, the brief is stale
  until someone clicks Rebuild. Time-based expiry is trivial to add but would spend tokens on
  briefs nobody reopened; a rebuild button the user controls seemed the better default.
- **Prior meetings come only from locally-synced Signals**, so history is bounded by what
  ingestion has seen (currently ~6-hourly).
- **No channel-scoped entry point yet** - `team_id` is plumbed through `prepare_meeting` and
  respected, but nothing in the Channel UI calls it. Wiring it is small once channel meetings
  matter.
- **No browser click-through** - standing caveat.

**Exit criteria:** one click on an upcoming meeting produces a grounded brief with linked sources
in seconds, costs at most one LLM call, costs nothing at all when there's no context to find, and
costs nothing on re-open. **All four confirmed, on both real and demo data.**

---

### Phase 2v — Attention Precision ✅ Built and tested (real-inbox precision ~17% → ~80%, zero added token cost)

**Objective:** the user proposed "Investigate This" as the second structured workflow. Analysis
said no - and measurement of the live feed said why. This phase fixed the feed instead of building
on top of it.

**Why this instead of a second workflow:** the real attention feed was surfacing **1 genuinely
actionable item out of 6** - the rest were job alerts and event marketing. Every downstream
feature (Catch Me Up, Channel Briefings, Prepare Me, and any future Investigate This) inherits
that noise. Building an investigation feature first would have meant shipping a way to deeply
investigate a .NET job alert.

Also weighed and rejected: "Investigate This" collapses further than it appears - `finding` items
already store `root_cause` and `suggested_action` (nothing to compute), `upcoming_meeting` is
covered by Prepare Me, `manual` items are user-written, and `deadline` items *are* emails. It
reduces to emails, where "Ask Sentinel ✨" already works.

| Step | Deliverable | Status |
|---|---|---|
| 2v.1 | Capture `List-Unsubscribe` + store `is_bulk` at ingestion | ✅ |
| 2v.2 | `services/mail_signals.py`: sender classification, repetition counting, high-signal rescue | ✅ |
| 2v.3 | **Measure against the real inbox before choosing any threshold** | ✅ |
| 2v.4 | Apply to the important-email and deadline detectors + duplicate suppression | ✅ |

### What actually got built (technical notes)

- **Measurement killed two confident hypotheses before they shipped.** I predicted
  `List-Unsubscribe` would be the headline signal (2024 bulk-sender rules make it near-mandatory)
  and that "is the user in `To:`?" would separate personal from blast. Measured on 259 real
  messages: the header was present on **1 of 33** flagged items, and direct-addressing was `True`
  for **every single message including bulk**. The first was kept as a weak-but-correct signal;
  the second was deleted rather than shipped as dead weight. Designing these on intuition would
  have produced a filter built on two non-signals.
- **What actually discriminates, in measured order:** (1) *repetition* - the same sender 3+ times
  in a week (5× abekus, 4× codebenders, 4× unstop, 15× unstop overall); (2) *automated local-part*
  (`noreply@`, `alert@`, `mailer-daemon@`), catching ~45% alone; (3) `List-Unsubscribe`, rare but
  unambiguous.
- **A more aggressive rule was built, measured, and deliberately discarded.** Adding bulk sending
  subdomains (`emails.`, `info.`, `content.`) cut 33 candidates to 3 - but among the casualties was
  *"Your domain has expired"*, the most actionable message in the inbox. Fewer items is not the
  goal. The conservative rule (33 → 8) shipped instead.
- **Measurement also caught a false negative in my own rule.** The repetition filter discarded a
  real *"Interview Invite from Planys Technologies"* because that job board had sent 9 messages
  that week. Fixed with a deliberately narrow `HIGH_SIGNAL_PHRASES` rescue - each phrase names a
  concrete commitment ("interview invite", "invoice", "has expired", "action required"), so
  marketing language like "Immediate Hiring – Apply Now!" matches none of them. It rescues from
  *repetition only*, never from an explicit mailing-list header.
- **Starring is never overridden.** An explicit human judgment about a specific message always
  beats a heuristic about its sender.
- **Duplicate suppression by (sender, subject)** - the same "domain expiring" notice arriving twice
  now occupies one slot.
- **Backwards compatible by construction:** messages ingested before this phase have no `is_bulk`
  key at all, so its absence means "unknown" and falls through to the sender heuristic - old rows
  degrade to prior behavior instead of being silently reclassified as clean.
- **Zero added token cost.** Every signal is a pure function over metadata already stored; no LLM,
  no extra network call. One header was added to an existing metadata fetch.

### Measured result (real inbox, 259 messages)

| | Before | After |
|---|---|---|
| Items surfaced | 6 | 5 |
| Genuinely actionable | ~1 | **4** |
| Precision | ~17% | **~80%** |

Gone: the "IPO closing today" promo (a false deadline), both job-alert spammers, and 4× repeated
hackathon marketing. Kept: both domain-expiry notices, a registration confirmation, and the
rescued interview invite. Demo workspace verified unchanged.

### Known gaps (deliberately deferred, not oversights)

- **Opted-in event marketing still slips through** - one remaining item ("1 Day Left to Register")
  comes from a single-send, human-looking sender. Killing it deterministically would risk real
  mail; the honest fix is dismissal-learning, which needs usage data that doesn't exist yet.
- **Dismissals still teach the detectors nothing.** Now that there's a `noise_reason` vocabulary,
  wiring "always mute this sender" is a small step - but it should be driven by what users actually
  dismiss, not predicted.
- **Thread participation is unused.** "Did the user reply in this thread?" is likely a strong
  signal, but `SENT` messages aren't ingested, so it couldn't be measured. Worth revisiting.
- **Tuned against one inbox.** The thresholds are honest for this data; a second real inbox could
  shift them.

**Exit criteria:** the feed surfaces mostly things that genuinely matter, every filtering decision
is explainable via `noise_reason`, nothing the user starred is ever hidden, and the change costs
no additional tokens. **All confirmed by measurement against the real inbox.**

---

### Phase 2w — Verification pass: two navigation-breaking bugs found and fixed ✅

**Objective:** stop shipping UI blind. Roughly twelve phases (2h, 2i, 2j, 2n, 2o, 2q, 2r, 2t, 2u)
each carried the line *"no browser click-through yet"*, while the user's own track record was
**4 for 4** - every single time they opened the app they found something broken (masked 500 on
calendar create, unreadable dark date picker, Drive dropdown wrecking the layout, Today's Brief
duplicating Attention). Verification was overdue, not optional.

Browser automation was unavailable, so this was done by production build + tracing the
expo-critical path through the code + replaying the whole flow through the API in frontend call
order. That was enough to find two bugs that no test could catch.

| Finding | Severity |
|---|---|
| Persona picker bounced every new user back to itself - app unreachable | **Critical** |
| Creating a workspace hung the dashboard on "Loading…" permanently | **High** |
| Latent: null active workspace could strand the dashboard in a loading state | Hardened |

### The bugs (both the same root cause)

**Contexts cache server state; mutating the server without refreshing the cache leaves the UI
reasoning about a stale world.** Two independent instances shipped:

1. **`OnboardingPage` never refreshed `OnboardingContext`.** It imported `refresh` from
   `useWorkspace()` - a different context entirely. So after saving a persona, `RequireAuth`
   re-evaluated against `onboarded_at: null`, decided the user hadn't onboarded, and redirected
   back to the picker. **Every new account, including every expo visitor, was trapped in a loop
   and could never reach the product.** The API confirmed the premise: re-reading `/onboarding`
   after the POST correctly returns `onboarded_at` set - the frontend simply never made that call.

2. **`CreateWorkspaceModal`'s `onCreated` called `setActiveId(w.id)` without refreshing the
   list.** `active` is resolved by finding `activeId` inside the cached `workspaces` array, so
   pointing at a workspace not yet in that array resolved to `null` - and `BriefPage`'s effect
   early-returned on null `active` *without clearing its loading flag*, leaving the dashboard
   stuck on "Loading…" with no recovery.

Both fixed by refreshing before navigating. `BriefPage` was additionally hardened to clear
`loading` when there is no active workspace, so this class of bug can degrade to a blank state
rather than a dead screen.

### What this validates

- **Tests measure functions, not products.** 160 tests were green across both bugs. Neither is
  detectable without either a browser or an explicit trace of the navigation gate - the app was
  provably unreachable for new users while every test passed.
- **A production build is not the same check as `tsc --noEmit`.** Ran `vite build` for the first
  time in the project's life; it passed, which is genuine (if narrower) information.
- **Replaying a flow through the API in frontend call order** is a cheap and effective substitute
  when browser automation isn't available - it proved the backend path end to end (gate → persona
  → demo seed → workspace list → attention → catch-up → prepare me) and isolated the failure to
  the client's cache handling.

### Known gaps (honest)

- **Still no actual browser click-through.** Rendering, layout, contrast, and interaction remain
  unverified by anyone but the user. This phase narrowed the gap; it did not close it.
- **No automated frontend tests exist at all.** Both bugs would have been caught by a single
  render test of the onboarding gate. Worth adding if this class recurs - not worth a testing
  framework decision made in passing.
- **Only the expo-critical path was traced.** Channel management, connection workspaces, and mail
  reading were not re-reviewed in this pass.

**Exit criteria:** the flow a first-time user takes actually works. **Two blocking bugs fixed;
backend path verified end to end; visual verification still pending a human.**

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
