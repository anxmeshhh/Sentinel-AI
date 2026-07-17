# Sentinel AI — Roadmap

**High-level status and sequencing.** For step-by-step detail, technical notes on what was
actually built, and known gaps per phase, see `PHASES.md` — this doc stays intentionally short so
it doesn't drift out of sync with that one; treat any conflict between the two as `PHASES.md`
being right.

Sequencing is deliberate: each phase only starts once the prior phase's exit criteria are met on
real data (see `PRD.md` §8), and — since `IA.md` v2 — once the underlying account/workspace/channel
mechanics exist to give that phase somewhere real to run. Building all 10 agents in parallel would
produce 10 shallow, untrustworthy agents instead of 2-3 that people actually rely on.

---

## Phase 1 — MVP: Prove the Core Loop ✅ Done

**Goal:** one real repo → one real, trusted finding.

- [x] Backend: FastAPI, **MySQL** (switched from the original Postgres plan), Celery/Redis
- [x] GitHub integration client (PRs, commits, issues, reviews; metadata only, no code)
- [x] Engineering Agent: review-latency trend, hotspot directories, contributor activity baseline, risky-deploy flags
- [x] LangGraph orchestrator: Engineering Agent → Executive Agent
- [x] Executive Agent: ranks findings, produces daily brief with root cause + suggested action
- [x] Groq LLM client (metrics-in, narrative-out; no raw data dumps)
- [x] React dashboard: brief, evidence drill-down, manual re-run, admin/observability panel
- [ ] Pilot on 3 repos with a real GitHub PAT (still only exercised with seeded/demo signals)

## Phase 1.5 / 1.6 / 1.7 — Personal Workspace, Auth, Wired Together ✅ Done

Not in the original plan — added once the product direction sharpened into "one account, many
Discord-style workspaces" (`IA.md` v2). Full detail in `PHASES.md`.

- [x] Personal Workspace as a second, real workspace kind (proved the workspace-scoping architecture generalizes)
- [x] Real auth: password + OTP, Google/Microsoft OAuth (coded, not yet exercised — needs your credentials), JWT sessions
- [x] Auth wired into every route — no more anonymous bootstrap fallback; real per-account tenant isolation, verified directly
- [x] Frontend: login/signup, dark single-family editorial theme, mobile-responsive shell

## Phase 2 — Workspaces as Servers, Teams as Channels, Cross-Tool Correlation

**Goal:** demonstrate the actual thesis — connecting dots *across* tools — on workspaces users
actually create and invite each other into, not seeded ones. Split into three parts (`PHASES.md`
has the full breakdown):

- **Phase 2a — the Discord core loop** (⏸ next up): create a workspace → create a Team
  (= channel, `IA.md` v2 §2.4) → generate an invite → someone joins. Open-by-default channels,
  invites at both workspace and channel scope.
- **Phase 2b — everything else already scoped for Phase 2**: `Project` model, real RBAC
  enforcement (not just "logged in or not"), Jira/Linear integration, Project Agent, Executive
  Agent compound findings, brief delivery beyond the dashboard.
- **Phase 2c — broaden beyond developers**: Gmail, Google Calendar, Google Meet, Zoom — so the
  onboarding "Connect Integrations" step (and Sentinel generally) serves non-engineering roles too,
  matching the original pitch. Sequenced after 2a so the workspace/channel UI ships complete first.

**Pilot exit criteria:** ≥1 compound finding a user says they wouldn't have caught themselves, ≥1
day early — on a workspace they created and invited a teammate into.

## Phase 3 — Communication + Knowledge Layer

- [ ] Communication Agent (Slack): gaps, unanswered questions, missing approvals
- [ ] Knowledge Agent (Notion/Confluence/Docs): staleness, missing docs, duplication
- [ ] Executive Agent incorporates both into brief ranking
- [ ] Organization-scale workspace pages (`IA.md` v2 §3.2's Executive/Command Center view at scale, Departments, Audit Logs)

**Estimated effort:** 3–4 weeks (Slack/Notion API integration + noisier signal handling).

## Phase 4 — Ops, Security, Finance, People

- [ ] DevOps Agent (Docker/K8s/logs/deploy alerts)
- [ ] Security Agent (credential leaks, dangerous commits, secret exposure)
- [ ] Finance Agent (cloud cost spikes, API usage, budget overruns)
- [ ] HR Wellbeing Agent — **opt-in only**, aggregate/team-level workload pattern signals (meeting load, context-switch frequency, response latency), explicitly no individual-level judgment output. Requires its own privacy review before shipping.
- [ ] Meeting Agent (transcripts → decisions, action items, forgotten tasks) — likely folds into Phase 2c's Google Meet/Zoom work rather than staying a separate later phase

**Estimated effort:** largest phase — likely reprioritized based on pilot user demand rather than
built in the listed order. Whichever agent pilot users ask for first should jump the queue.

## Beyond Phase 4

- Guest role, Super Admin/platform administration tier (the existing Admin panel needs this before
  it's safe in a multi-tenant world — flagged in `PHASES.md`)
- Multi-tenant billing infrastructure once there's pull from users beyond friendly pilots
- Autonomous *actions* — the DETECT→ACT pipeline's last two stages (`IA.md` v2 §5): an agent
  proposing a change to an external system, gated behind human approval, never default-on
- GitHub App migration (from PAT) for scale and narrower permission scopes

---

## Guiding rule for sequencing

Do not start building a new agent until the current agent's findings have been validated as
accurate by a real user on real data. An unvalidated agent adds noise, and noise is the #1 way
this product category loses trust (see `PRD.md` §9 risks). The same discipline now applies one
level up: don't add integration breadth (Phase 2c) or agent breadth (Phase 3/4) before the
workspace/channel mechanics they'll run on (Phase 2a) actually work end to end.
