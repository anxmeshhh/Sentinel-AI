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

## Phase 1 — MVP Core Loop

**Objective:** one connected GitHub repo produces one real, trusted finding, surfaced in a working
dashboard. Everything else in the system is inert until this loop is proven.

**IA surface that goes live:** the Organization Workspace nav (`IA.md` §2.4), with only what's
built actually shown — Dashboard (Today's Brief), Agent Center (Engineering + Executive only),
Settings (Connections). Personal Workspace, Team Workspace, RBAC, and the other 7 agents stay
hidden, not partially built.

| Step | Deliverable | Notes |
|---|---|---|
| 1.1 | Backend scaffold | `backend/` FastAPI app, Postgres models (`connections`, `signals`, `findings`, `briefs`, `agent_runs` per `ARCHITECTURE.md` §3), Celery + Redis config, `docker-compose.yml`, `.env.example` |
| 1.2 | GitHub integration client | PAT-based, pulls PRs/commits/issues/reviews **metadata only** (no source/diffs — hard constraint from `PRD.md` §7), incremental sync via `last_synced_at` |
| 1.3 | Engineering Agent | Computes review-latency trend, file hotspots, contributor-activity baseline, risky-deploy flags; hands pre-computed metrics (not raw dumps) to the LLM for narrative + confidence scoring |
| 1.4 | Groq LLM client | Single-file wrapper (`llm.py`) so the provider is swappable later without touching agent logic |
| 1.5 | Executive Agent + LangGraph orchestrator | `StateGraph` with `engineering_agent → executive_agent` fan-in; ranks findings by severity × confidence; produces the daily brief |
| 1.6 | FastAPI endpoints + Celery beat | `POST /connections`, `POST /runs` (manual re-run), `GET /briefs/latest`, `GET /findings/{id}`; scheduled poll every 6h |
| 1.7 | React dashboard | Connect screen, Today's Brief, Finding Detail (evidence drill-down), History, Settings — matches the approved walkthrough artifact |
| 1.8 | Local dev + smoke test | `docker-compose up`, run against a real repo with a real `GROQ_API_KEY`, confirm end-to-end brief generation |

**Exit criteria (from `PRD.md` §8):** 3 real repos connected (yours + 2 pilots); each produces at
least one finding the repo owner independently confirms is accurate.

**⏸ Wait for signal before Phase 1.5.**

---

## Phase 1.5 — Personal Workspace

**Objective:** prove Sentinel works for an individual with no team behind them — the "for
themselves as well" case from your IA brief, on the smallest possible surface.

**IA surface that goes live:** Personal Workspace (`IA.md` §2.2) — Dashboard, AI Assistant,
Timeline, Integrations (personal-account scope), Notifications, Profile. Tasks/Calendar/Insights
can stay stubbed until real signal sources justify them (see open question below).

| Step | Deliverable | Notes |
|---|---|---|
| 1.5.1 | Data model: `users`, `workspaces`, `memberships` | Shaped for the full RBAC model now (per `IA.md` §6 architectural note) even though only one implicit role exists until Phase 2 |
| 1.5.2 | Personal-scope GitHub connection | Same client as Phase 1, re-pointed at a user's own account instead of an org repo |
| 1.5.3 | Personal Dashboard | Engineering + Executive agents re-scoped to one person's activity |
| 1.5.4 | AI Assistant (chat) | The one place a chat interface is primary — scoped to the user's own data, explicitly secondary to the pushed brief per `PRD.md` principle #1 |
| 1.5.5 | Workspace switcher (UI) | Minimal version: Personal only for now, structured so Team/Org tabs slot in without rework (per the IA explorer artifact) |

**Exit criteria:** a solo user (no team, no org) can connect their own GitHub account and receive a
personal daily brief through the same pipeline used in Phase 1.

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
