# Sentinel AI — Information Architecture

**Status:** v2 — target end-state IA, revised from v1 to the Discord-server workspace model. See §8
for what changed from v1 and why, and how this reconciles with what's actually been built
(`PHASES.md`).

---

## 1. Design Model: One Account, Many Workspaces

Sentinel works the way Discord or Slack does, not the way a single-tenant SaaS dashboard does: a
user has **one global account**, and can belong to **any number of Workspaces** — created, joined
by invitation, or (for exactly one) auto-provisioned as their private space.

```
USER ACCOUNT
│
├── Personal Space        — auto-created, private, always exists, kind=personal
├── Acme Corporation       — created or joined, kind=organization
├── Webnify                — created or joined, kind=organization
└── College Team           — created or joined, kind=organization
```

**Every Workspace — Personal Space included — has the identical page structure** (§3.2). Personal
Space isn't a structurally different thing from Acme Corporation; it's a Workspace with one member
(you) and, until you add some, zero Teams and Projects. This is the single biggest simplification
over v1, which had three *structurally different* page sets for Personal/Team/Organization. One
page set, reused everywhere, just with different data and different peers — same principle v1 had
for the Agent page contract, now applied to the Workspace itself.

**Teams and Projects are no longer workspace-level peers — they live inside a Workspace**, as
first-class entities with their own membership and their own pages (§3.4, §3.5):

```
WORKSPACE (e.g. Acme Corporation)
│
├── Members                     — everyone with access to this workspace
├── Teams                       — Backend, Frontend, AI, DevOps, ...
│     └── Team Members          — a user can be on multiple teams
├── Projects                    — Payment System, Internal Tools, ...
│     ├── Assigned Team(s)
│     └── Assigned Member(s)
├── Strategic Initiatives       — a named grouping of multiple Projects
├── Integrations                — GitHub, Jira, Slack, Notion, Calendar, ... (workspace-scoped)
└── Sentinel Intelligence       — the AI Agents' findings, scoped to this workspace
```

A user can belong to multiple Workspaces, multiple Teams within a Workspace, and multiple Projects
within a Workspace — all independently.

## 2. Auth & Onboarding Flows

### 2.1 Sign up / Login

Google · Microsoft · Email — all land in the same place post-auth: **Sentinel Home** (§3.1), the
global, workspace-agnostic screen showing the account's Workspace list and the workspace switcher.

### 2.2 New account → first decision

Two options, always both available (not mutually exclusive over time — an account can do both):

- **Create a Workspace** — the creator becomes **Workspace Owner/Admin** (§4). Creation is a short
  wizard: name, logo, organization type, industry, team size, primary use cases (e.g. "Project
  Intelligence," "Engineering Visibility," "Risk Detection," "Team Coordination") — these inputs
  don't just decorate the workspace, they set sensible defaults for which AI Agents are
  pre-enabled and which Integrations are suggested first.
- **Join a Workspace** — via an invitation link. Login/signup if not already authenticated → view
  the invitation ("X has invited you to join Acme Corporation") → Accept → the workspace appears
  in the switcher, and the invite determined the joining user's initial Role, Team(s), and Project
  access.

### 2.3 Workspace onboarding (Owner/Admin only, right after creation)

A fixed sequence, each step skippable/revisitable later from Workspace Settings:

1. Connect Integrations (GitHub, Jira, Slack, Notion, Google Calendar, ...)
2. Invite Members
3. Assign Roles
4. Create or import Teams
5. Create or import Projects
6. Assign Members and Teams to Projects
7. Sentinel begins analyzing authorized workspace data — this is the moment ingestion + the AI
   Agents actually turn on for this workspace; everything before this step is configuration only.

### 2.4 Teams Are Channels: the Join Model

Explicit decision, made when this got planned for real: **a Team *is* Sentinel's Discord-channel
equivalent**, not a separate concept. A Workspace is a server; each Team inside it is a channel.
This isn't a new entity on top of §1's model — it's naming what was already there.

- **Open by default**: any Workspace member can see and join any Team in that workspace without an
  invite, the way public Discord channels work. Private/invite-only Teams are a future exception,
  not the default.
- **Invites exist at two scopes**: a **Workspace invite link** ("join Acme Corporation," no Team
  assignment yet) and a **Team invite link** ("join Acme Corporation, land directly in Backend
  Team") — both are the same underlying invite object, a Team invite is just a Workspace invite
  with a `team_id` set. Accepting either always creates the Workspace `Membership`; a Team-scoped
  one additionally creates the `TeamMembership`.
- **Creating a Team** requires being a Workspace member (any role, for now — no Owner-only
  restriction at MVP, since gating that meaningfully needs Phase 2's real RBAC enforcement anyway).

## 3. Full Sitemap

### 3.1 Public + Sentinel Home

| Page | Purpose |
|------|---------|
| Home / Features / Pricing / Documentation / Blog / Contact | Public marketing, unchanged from v1 |
| Login / Sign Up | Google, Microsoft, or Email |
| **Sentinel Home** *(new in v2)* | Post-auth landing: the account's Workspace list, workspace switcher, "Create / Join Workspace" entry point — this is the "Discord app before you click into a server" screen. Not itself scoped to any workspace. |

### 3.2 Inside a Workspace (the one page set, used by every workspace)

| Page | Purpose |
|------|---------|
| Overview / Command Center | Workspace-wide health — replaces v1's separate "Executive Dashboard" and "Team Dashboard," now one page type reused at every scope |
| **My Work** *(new in v2)* | The user's personal operational view **within this workspace**: tasks assigned to them, PRs needing attention, deadlines, meetings, blockers, notifications, and an AI-generated priority list. This replaces v1's Personal-Workspace-as-a-separate-thing — "My Work" is what a Personal Space's home page effectively *is*, but now available inside every workspace, not just a standalone Personal one. |
| Projects | This workspace's project list |
| Teams | This workspace's team list |
| Intelligence | The Intelligence Feed (§5) — risks, bottlenecks, blocked work, cross-team dependencies, anomalies, recommended actions |
| Alerts | Time-ordered notification stream, workspace-scoped |
| Analytics | Productivity, project, and team performance trends |
| Ask Sentinel | The AI copilot (renamed from v1's "AI Assistant" — same feature, same grounding discipline: answers only from data the *asking user* is authorized to see) |
| AI Agents | Per-agent status/config — the v1 Agent Center, reframed around the DETECT→ACT pipeline (§5) |
| Integrations | This workspace's connections |
| Workspace Settings | Members, Roles, Permissions, Billing, the onboarding steps (§2.3), revisited |

The visible subset of this list depends on the viewing user's Role (§4) — a Guest sees a tiny
slice; an Owner sees all of it. Same principle as v1 §5's "RBAC is a lens over the same IA."

### 3.3 Cross-cutting note: what happened to "Agent Center"

v1 had a flat `Executive · Engineering · Project · Communication · Knowledge · Security · DevOps ·
HR · Finance` list under "Agent Center." That page contract (Status, Findings, Recommendations,
History, Confidence, Evidence) **still stands unchanged** — it's now reached via the workspace's
**AI Agents** page instead of a separately-named top-level section, and each agent additionally
declares its position in the DETECT→ACT pipeline (§5).

### 3.4 Team page (opening a specific Team inside a Workspace)

| Page | Purpose |
|------|---------|
| Overview | Team health snapshot |
| Projects | This team's active projects |
| Work | Open/blocked tasks for the team |
| Members | Roster |
| Activity | Recent team activity |
| Insights | Team workload, progress, upcoming deadlines, team-level risks — the Engineering/Communication agents' output, scoped to this one team |

### 3.5 Project page (opening a specific Project inside a Workspace)

| Page | Purpose |
|------|---------|
| Overview | Project status |
| Tasks | Task list |
| Timeline | Schedule/milestones |
| Team | Assigned team(s) and member(s) |
| GitHub Activity | PRs, commits, reviews for this project's repo(s) |
| Dependencies | Cross-project/cross-team dependencies |
| Risks | Findings scoped to this project |
| AI Insights | The pitch made concrete: instead of checking Jira → GitHub → Slack → Notion separately, this one page combines all of it — Sentinel's core "connect the dots" value proposition, at project granularity. |

## 4. RBAC Model (v2 — more granular than v1)

v1 had five roles. This splits "Org Admin" into **Owner/Admin** + **Executive**, and splits "Team
Manager" into **Manager** + **Team Lead**, matching the workflow spec's org chart more precisely.
Super Admin (platform-wide operator access) and Guest are carried over from v1 unchanged — the
workflow spec didn't mention either, but both are still structurally necessary: Super Admin is
exactly what the existing Admin & Observability panel (`PHASES.md` Phase 1 addendum) needs to be
gated behind once this ships, and Guest is still the narrowest real-world tier (an external
contractor, a client given one project's visibility).

| Role | Scope | Can do |
|------|-------|--------|
| **Super Admin** | Platform-wide | Everything, including platform administration across every workspace |
| **Workspace Owner/Admin** | One Workspace | Manage the workspace, members, roles, integrations, AI Agent configuration; full workspace intelligence |
| **Executive** | One Workspace | Command Center, Strategic Initiatives, workspace-wide Analytics, high-level Intelligence — read-heavy, cross-team, not workspace configuration |
| **Manager** | Managed Teams/Projects | Their Teams' and Projects' intelligence, analytics, and work — narrower than Executive, broader than Team Lead |
| **Team Lead** | Own Team | Their one Team's page (§3.4), its Projects, workload, risks |
| **Member/Developer** | Self + their Teams/Projects | My Work, their Teams, their assigned Projects, Ask Sentinel, relevant Intelligence |
| **Guest** | Explicitly assigned only | One or more assigned Projects, shared Reports, limited Ask Sentinel — no workspace-wide visibility |

### Permission matrix

| Page / Section | Super Admin | Owner/Admin | Executive | Manager | Team Lead | Member | Guest |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| My Work | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Overview / Command Center | ✓ | ✓ | ✓ | Read | Read (own team) | — | — |
| Teams (own) | ✓ | ✓ | ✓ | ✓ | ✓ | Read | — |
| Teams (other) | ✓ | ✓ | ✓ | Managed only | — | — | — |
| Projects (assigned) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ (explicit grant) |
| Projects (all) | ✓ | ✓ | ✓ | Managed only | — | — | — |
| Intelligence (workspace-wide) | ✓ | ✓ | ✓ | Managed scope | Own team | — | — |
| Analytics | ✓ | ✓ | ✓ | Managed scope | Own team | — | — |
| Ask Sentinel | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | Limited |
| AI Agents (config) | ✓ | ✓ | Read | — | — | — | — |
| Integrations | ✓ | ✓ | Read | — | — | — | — |
| Workspace Settings / Billing | ✓ | ✓ | — | — | — | — | — |
| Platform Administration | ✓ | — | — | — | — | — | — |

## 5. AI Agents: the DETECT → ACT pipeline

Every agent's work follows the same six-stage pipeline. This is the target design; **Phase 1's
Engineering + Executive agents currently only implement the first four stages** (see reconciliation
below) — read-only intelligence is the default, matching the workflow spec's own framing.

```
DETECT → ANALYZE → EXPLAIN → RECOMMEND → REQUEST APPROVAL → ACT
```

- **Detect / Analyze / Explain / Recommend** — this is everything Sentinel does today: deterministic
  candidate detection, LLM-narrated root cause, a suggested action. No system state changes.
- **Request Approval / Act** — an agent proposing to *change something in an external system* (e.g.
  auto-reassign a reviewer, open a Jira ticket) first surfaces a request; a human with the right
  Role approves or rejects it before anything executes. This was v1's "Beyond Phase 4: autonomous
  actions, gated per opt-in" — same constraint, now named as two concrete pipeline stages instead
  of a vague future bullet, so when the time comes there's a clear place to build it (an
  `agent_actions` table with a `requested → approved/rejected → executed` status, mirroring how
  `agent_runs` already tracks `running → success/partial/failed`).

## 6. Navigation Model

- **Sentinel Home** (§3.1) is the account-level landing screen — not itself a workspace.
- **Workspace switcher**: every Workspace the account belongs to, plus a `[+] Create / Join
  Workspace` entry. Selecting one swaps the entire app context — sidebar, Intelligence, Ask
  Sentinel's grounding data, everything — the same "swap the whole shell" principle as v1, just
  applied uniformly instead of only across three fixed kinds.
- **URL scheme** (supersedes v1 §4's):
  ```
  /                                          → public marketing
  /login, /signup                            → auth
  /home                                      → Sentinel Home (workspace list/switcher)
  /workspaces/new                            → Create Workspace wizard
  /workspaces/join/:inviteToken              → Join Workspace flow
  /w/:workspaceSlug/...                      → inside a workspace (Overview, My Work, Projects, Teams, Intelligence, Alerts, Analytics, Ask Sentinel, AI Agents, Integrations, Settings)
  /w/:workspaceSlug/teams/:teamSlug/...      → Team page (§3.4)
  /w/:workspaceSlug/projects/:projectSlug/...→ Project page (§3.5)
  ```

## 7. Why This Shape

- **One Workspace page set, not three** — a Personal Space and a 200-person org render the exact
  same page types; only the data (and the Role lens, §4) differs. This is strictly simpler than v1
  and was the main thing worth revising.
- **Teams/Projects as entities, not workspace kinds** — lets a single workspace contain an
  arbitrary number of each, matching how real orgs are actually shaped (v1's `WorkspaceKind.TEAM`
  modeled a team *as if* it were its own workspace, which doesn't match "Backend Team lives inside
  Acme Corporation").
- **RBAC still a lens over one IA**, just a more granular lens now (§4) — the permission matrix
  grew rows, not page types.
- **The DETECT→ACT pipeline gives "autonomous actions" a concrete home** to be built into later,
  instead of leaving it as an unshaped future bullet.

## 8. Reconciling With What's Actually Been Built

### 8.1 What changed from v1, and why

| v1 concept | v2 replacement | Why |
|---|---|---|
| Personal / Team / Organization as three structurally different workspace kinds | One Workspace page set, reused by every workspace (Personal Space included) | Simpler; matches the Discord-server model in the workflow spec directly |
| `WorkspaceKind.TEAM` (a Team *as* a Workspace) | `Team` as a new entity living inside a Workspace | Matches how real orgs nest (Acme Corp → Backend Team), not how v1 flattened it |
| "AI Assistant" | "Ask Sentinel" | Same feature, workflow spec's naming — a rename to apply next time that code is touched, not urgent on its own |
| RBAC: 5 roles | RBAC: 7 roles (Owner/Admin and Executive split out; Manager and Team Lead split out) | Matches the workflow spec's org chart precisely |
| "Beyond Phase 4: autonomous actions" (unshaped) | DETECT→ACT pipeline, concrete `agent_actions` state machine (§5) | Gives the eventual action-approval feature a real design instead of a placeholder |

### 8.2 Good news: the current data model mostly already fits

Phase 1/1.5's `Workspace` + `Membership` tables (`ARCHITECTURE.md` §3) were already built as
"however many workspaces, each with role-tagged memberships" — **not** hardcoded to one workspace
per user. Proving that generality was the entire point of Phase 1.5 (`PHASES.md`). What's actually
missing to build v2 for real:

1. **Real auth** (Google/Microsoft/Email, sessions) — currently there is none; every request
   resolves to one implicit user (`core/bootstrap.py`). This is the true prerequisite for
   everything else in this document — workspace creation/invites/roles are all meaningless without
   real accounts to attach them to.
2. **Workspace CRUD + invites** — `POST /workspaces` (create), `POST /workspaces/:id/invites`,
   `POST /invites/:token/accept` don't exist yet; today's two workspaces are bootstrap-seeded, not
   user-created.
3. **`Team` and `Project` models** — genuinely new tables, don't exist yet. `Finding`/`Signal`
   already scope to `workspace_id`; they'll need an optional `team_id`/`project_id` to power the
   Team and Project pages' scoped Intelligence.
4. **Role enforcement** — the `Role` enum already has values close to v2's set (`ARCHITECTURE.md`
   §3), but nothing currently *checks* role on any route. Real enforcement needs real auth (#1)
   first.
5. **Rename `WorkspaceKind.TEAM`'s role** — not urgent, but the enum value should stop being used
   for "a team" once the real `Team` entity exists, to avoid two different things both being called
   "team" in the schema.

See `PHASES.md` for how this gets sequenced into actual build phases.
