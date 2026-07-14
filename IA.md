# Sentinel AI — Information Architecture

**Status:** Draft v1 — target end-state IA. See §6 for how this reconciles with the phased MVP in `ROADMAP.md`.

---

## 1. Design Model: Workspaces, Not Pages

Sentinel is navigated the way Linear, Notion, and GitHub are: a **workspace switcher** at the top
of the shell determines what the surrounding navigation, dashboards, and agent findings are
*scoped to*. The same page type (a Dashboard, an Agent Center, a Reports page) exists in multiple
workspaces, but shows different data and different peers depending on which workspace is active.

Every user always has exactly one **Personal Workspace**. They additionally belong to zero or more
**Team Workspaces** and, if their company has onboarded Sentinel org-wide, one **Organization
Workspace**. This is what makes Sentinel work "not only for the company but for themselves as
well" — an individual with no team can still get a personal AI assistant and daily brief; a
company that adopts it org-wide layers Team and Organization workspaces on top of the same
underlying account.

```
Sentinel
├── Public (no auth)
├── Personal Workspace          — always present, one per user
├── Team Workspace(s)           — zero or more, one per team the user belongs to
├── Organization Workspace      — present once a company has onboarded org-wide
├── Agent Center                — cross-cutting, scoped to whichever workspace is active
├── Analytics                   — cross-cutting, scoped to whichever workspace is active
├── Integrations                — cross-cutting, scoped to whichever workspace is active
├── Notifications                — cross-cutting, scoped to whichever workspace is active
└── Settings                     — Personal settings + Organization settings
```

## 2. Full Sitemap

### 2.1 Public (no login)

| Page | Purpose |
|------|---------|
| Home | Positioning, the "digital COO" pitch |
| Features | The 10-agent story, by workspace type |
| Pricing | Personal / Team / Organization tiers |
| Documentation | Setup guides, integration docs, agent reference |
| Blog | Findings-driven content marketing (real anonymized brief examples) |
| Contact | Sales/support contact |
| Login / Sign Up | Auth entry points |

### 2.2 Personal Workspace

| Page | Purpose |
|------|---------|
| Dashboard | AI-generated personal overview — today's brief, scoped to you |
| Tasks | AI-prioritized tasks and to-dos, pulled from connected tools |
| Calendar | Meetings, deadlines, schedule |
| Insights | Personal productivity trends and AI observations |
| AI Assistant | Chat surface — the one place a chat UI is primary, scoped to your own data |
| Timeline | Daily activity history, chronological |
| Integrations | Connect GitHub, Gmail, Calendar, Notion, etc. (personal-account scope) |
| Notifications | AI alerts and reminders |
| Profile | Personal settings |

### 2.3 Team Workspace

| Page | Purpose |
|------|---------|
| Team Dashboard | Overall team health |
| Members | Team roster and workload |
| Projects | Active projects |
| Sprint Board | Sprint progress and risk |
| Agent Center (team-scoped) | Status of agents running against this team's data |
| Team Timeline | Team events |
| Reports | Weekly/monthly summaries |

### 2.4 Organization Workspace

| Page | Purpose |
|------|---------|
| Executive Dashboard | Company-wide health — the Executive Agent's primary surface |
| Departments | Engineering, HR, Finance, etc. |
| Projects | Cross-team project roll-up |
| Teams | All teams in the org |
| Employees | Org-wide people directory |
| AI Insights | Org-wide findings roll-up |
| Incident Center | Active incidents across departments |
| Reports | Org-wide summaries |
| Integrations | Org-wide connections (as opposed to personal-account connections) |
| Audit Logs | Who did what, when — compliance surface |
| Organization Settings | Org-wide configuration |

### 2.5 Agent Center (cross-cutting)

One entry per agent; which agents appear depends on the active workspace (a Personal Workspace
only ever shows Executive + Engineering + Knowledge, for example — Security/DevOps/Finance are
meaningless without a team or org behind them).

Executive · Engineering · Project · Communication · Knowledge · Security · DevOps · HR · Finance

**Every agent page shares one contract**, so the pattern is learned once and reused nine times:

| Block | Content |
|-------|---------|
| Status | Active/paused, last run time, data sources currently connected |
| Findings | Current findings, ranked by severity × confidence |
| Recommendations | Suggested actions tied to each finding |
| History | Past findings and whether they were resolved, dismissed, or are still open |
| Confidence | The score methodology, and the agent's accuracy trend over time (validates or erodes trust) |
| Evidence | The raw signals behind every finding above — the explainability layer |

### 2.6 Analytics (cross-cutting)

Productivity · Project Analytics · Team Performance · AI Predictions · Trends

Scoped like Agent Center: Personal shows your own trends, Team shows team performance, Org shows
company-wide trends.

### 2.7 Integrations (cross-cutting)

GitHub · Jira · Linear · Slack · Notion · Google Workspace · Microsoft 365 · Zoom · Docker ·
Kubernetes

A connection made in the Personal Workspace (e.g., your own GitHub account) is distinct from one
made in the Organization Workspace (e.g., the company's GitHub org) — same integration, different
scope and credential.

### 2.8 Notifications (cross-cutting)

AI Alerts · Recommendations · Tasks · Mentions · Incident Updates

### 2.9 Settings

| Personal | Organization |
|----------|--------------|
| Profile | Members |
| Security | Roles |
| API Keys | Permissions |
| Preferences | Billing |
| | Workspaces |

## 3. RBAC Model

| Role | Scope | Can do |
|------|-------|--------|
| **Super Admin** | Platform-wide | Everything, including platform administration (cross-org, billing infra, feature flags) |
| **Organization Admin** | One Organization | Everything in that org except platform administration |
| **Team Manager** | One or more Teams | Team Dashboard, Members, Projects, Reports, Agent Center — for their own team(s) only |
| **Employee** | Self + teams they belong to | Personal Dashboard, My Tasks, My Projects, AI Assistant, Calendar, Notifications; read-only visibility into their team's shared pages |
| **Guest** | Explicitly assigned items only | Assigned Projects, Shared Reports, a limited AI Assistant, and a single standing AI suggestion — no dashboard, no org visibility |

### Permission matrix

| Page / Section | Super Admin | Org Admin | Team Manager | Employee | Guest |
|---|:---:|:---:|:---:|:---:|:---:|
| Personal Workspace | ✓ | ✓ | ✓ | ✓ | — |
| Team Workspace (own team) | ✓ | ✓ | ✓ | Read | — |
| Team Workspace (other teams) | ✓ | ✓ | — | — | — |
| Organization Workspace | ✓ | ✓ | — | — | — |
| Agent Center (personal-scoped) | ✓ | ✓ | ✓ | ✓ | — |
| Agent Center (team/org-scoped) | ✓ | ✓ | Own team | Read (own team) | — |
| Analytics (team/org) | ✓ | ✓ | Own team | — | — |
| Audit Logs | ✓ | ✓ | — | — | — |
| Organization Settings / Billing | ✓ | ✓ | — | — | — |
| Platform Administration | ✓ | — | — | — | — |
| Assigned project (explicit grant) | ✓ | ✓ | ✓ | ✓ | ✓ |

## 4. Navigation Model

- **Workspace switcher**, top-left of the app shell (à la Linear's team switcher / Slack's
  workspace switcher): lists Personal + every Team the user belongs to + the Organization (if any),
  and swaps the entire left sidebar's contents when changed.
- **Left sidebar** contents are workspace-dependent (§2.2–2.4), but **Agent Center, Analytics,
  Integrations, Notifications, and Settings always appear** in every workspace — their content is
  simply re-scoped, not restructured, which is what lets a user's mental model transfer between
  Personal and Team/Org without relearning navigation.
- **URL scheme** (for the eventual frontend router):
  ```
  /                                    → public marketing
  /login, /signup                      → auth
  /app/personal/...                    → Personal Workspace
  /app/team/:teamSlug/...              → Team Workspace
  /app/org/:orgSlug/...                → Organization Workspace
  /app/{scope}/{scopeId}/agents/:agentSlug   → Agent Center, scoped
  /app/{scope}/{scopeId}/analytics/...       → Analytics, scoped
  /app/{scope}/{scopeId}/settings/...        → Settings, scoped
  ```

## 5. Why This Shape

- **One page contract for all 9 specialist agents** (§2.5 table) means building the 3rd agent's UI
  is a data-binding exercise, not a design exercise — the Roadmap's agent-by-agent sequencing
  (`ROADMAP.md`) produces a new Agent Center entry each time, not a new page type.
- **Cross-cutting sections scoped by workspace** (rather than duplicated per workspace) keep the
  nav from tripling in size as Team and Organization workspaces come online.
- **RBAC is a lens over the same IA, not a separate IA per role** — a Guest and a Super Admin see
  structurally the same kind of app, just with almost everything dimmed or hidden. This avoids
  building five different UIs.

## 6. Reconciling With the Phased MVP (`PRD.md` / `ROADMAP.md`)

This document describes the **full target IA**. It is broader than the current MVP scope on
several axes the original PRD explicitly deferred: multi-tenancy, RBAC, and a personal (individual,
non-org) use case were all listed under "beyond Phase 4." That's a real scope delta worth naming,
not quietly absorbing.

**Recommendation — build this IA as a strict subset at each phase, so navigation is never
rebuilt, only unhidden:**

| Phase | What's live in this IA | What's still hidden |
|-------|------------------------|----------------------|
| **Phase 1 (current MVP)** | One implicit workspace (= one org, one admin user, no role picker yet). Sidebar: Dashboard (Today's Brief) + Agent Center (Engineering, Executive only) + Settings (Connections). This *is* the Organization Workspace nav from §2.4, with every other section not yet built simply absent from the sidebar. | Personal Workspace, Team Workspace, RBAC, remaining 7 agents |
| **Phase 1.5** | Personal Workspace goes live — the same Engineering + Executive agent logic, re-scoped to one person's own connected GitHub account instead of a team's repo. This is the "for themselves as well" case, and validates the workspace-scoping model early, on the smallest possible surface. | Team Workspace, RBAC beyond a single implicit admin |
| **Phase 2** | Team Workspace + Project Agent (per original Roadmap Phase 2) + first real RBAC roles (Org Admin, Team Manager, Employee) — this is when access control starts mattering, since Phase 1/1.5 only ever have one user. | Organization Workspace (departments, audit logs, exec dashboard), Guest role, remaining agents |
| **Phase 3** | Communication + Knowledge agents (per original Roadmap Phase 3), Organization Workspace comes online (Executive Dashboard, Departments, Audit Logs). | DevOps/Security/Finance/HR agents, Guest role, Super Admin/platform tier |
| **Phase 4** | DevOps, Security, Finance, HR Wellbeing agents (per original Roadmap Phase 4). | Guest role, Super Admin/platform tier, billing infra |
| **Beyond Phase 4** | Guest role, Super Admin/platform administration, multi-tenant billing infra — unchanged from the original Roadmap's "Beyond Phase 4" section. | — |

**Architectural consequence to flag now:** even though Phase 1 only exercises "one org, one admin,
no roles," the data model should be shaped for workspaces/memberships/roles from the start
(`users`, `workspaces`, `memberships` with a `role` column) rather than a flat single-tenant
table — so Phase 2's RBAC is additive logic on an existing shape, not a schema rewrite. This is the
same principle `ARCHITECTURE.md` already applies to the Agent/LangGraph contract; when
implementation resumes, `ARCHITECTURE.md` §3 (Data Model) needs a pass to reflect this before any
backend code is written, so Phase 1 doesn't build itself into a corner.
