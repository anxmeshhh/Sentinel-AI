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
