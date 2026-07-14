# Sentinel AI — Architecture & Strategy

**Status:** v1.1 — implementation underway for Phase 1. Updated from v1 to reflect two decisions
made after the original draft: the database is **MySQL**, not Postgres (§2, §3), and the data
model now bakes in workspace scoping + RBAC shape from row one, per `IA.md` §6's note that this
needed to happen before backend code was written.

---

## 1. High-Level Shape

```
                     ┌─────────────────────────────────────────────┐
                     │              Integrations Layer               │
                     │  GitHub | Jira | Slack | Notion | ... (later) │
                     └───────────────────┬─────────────────────────┘
                                         │  poll / webhook
                                         ▼
                     ┌─────────────────────────────────────────────┐
                     │            Ingestion Workers (Celery)         │
                     │  normalize raw API data → Signal rows in DB   │
                     └───────────────────┬─────────────────────────┘
                                         ▼
                     ┌─────────────────────────────────────────────┐
                     │                   MySQL                       │
                     │ workspaces | connections | signals | findings │
                     │  | briefs | agent_runs                        │
                     └───────────────────┬─────────────────────────┘
                                         ▼
                     ┌─────────────────────────────────────────────┐
                     │        Agent Orchestration (LangGraph)        │
                     │                                                │
                     │   Engineering Agent ──┐                        │
                     │   Project Agent ──────┼──▶ Executive Agent     │
                     │   Communication Agent ─┘   (synthesis/brief)   │
                     └───────────────────┬─────────────────────────┘
                                         ▼
                     ┌─────────────────────────────────────────────┐
                     │                FastAPI (REST)                 │
                     └───────────────────┬─────────────────────────┘
                                         ▼
                     ┌─────────────────────────────────────────────┐
                     │           React Dashboard (Vite)              │
                     └─────────────────────────────────────────────┘
```

Each specialized agent is a **producer of structured Findings**, not a chatbot. The Executive
Agent is the only agent that produces the user-facing **Brief**. This keeps every specialist agent
independently testable (given the same Signals, does it produce the Findings a human would agree
with?) and keeps the synthesis logic (severity ranking, cross-agent correlation) in one place.

## 2. Why this stack

| Choice | Reasoning |
|--------|-----------|
| **FastAPI** | Async-native, typed, minimal ceremony for a data/agent-heavy backend. Good fit for both the REST API and the Celery task definitions living in the same codebase. |
| **Celery + Redis** | Ingestion (polling GitHub) and agent runs are background jobs on a schedule, not request/response work. Celery Beat gives cron-like scheduling; Redis is both the broker and, later, a place to cache expensive intermediate signals. |
| **MySQL** | Findings/briefs are structured, relational, and need to be queried/joined (e.g., "all findings referencing PR #123") — not a good fit for a pure document store. Chosen over Postgres to match the operator's existing MySQL setup; the ORM layer uses SQLAlchemy's backend-agnostic `Uuid`/`JSON` types rather than Postgres-only `UUID`/`JSONB`/`ARRAY`, so semi-structured evidence payloads still work, just without JSONB's containment-query features (not needed — nothing queries *inside* a payload at the DB level, it's always read whole). |
| **LangGraph** | The product shape *is* a graph: N specialist agents feed one synthesis agent, and Phase 2 adds cross-agent edges (Project Agent's findings modify how Executive Agent weighs Engineering Agent's findings). LangGraph models this explicitly as a graph with shared state, rather than hand-rolling orchestration logic. It's LLM-provider-agnostic, so swapping Groq for another provider later doesn't require re-architecting. |
| **Groq (`openai/gpt-oss-120b`, via the official `groq` SDK)** | Only LLM credential currently available; also a genuine fit — Groq's inference speed matters because the Executive Agent's job is to synthesize on a schedule across potentially many agents' worth of findings, and fast, cheap inference keeps that loop tight. The SDK call is isolated in a single `agents/llm.py` client with zero LangChain coupling, so switching model/provider later is a one-file change; LangGraph (above) handles orchestration independently of which LLM SDK is behind it. |
| **React + Vite + Tailwind** | Standard, fast-to-build dashboard stack; no need for Next.js SSR since this is an authenticated internal dashboard, not a marketing site — Vite keeps the dev loop simple. |
| **Docker Compose (local), single-tenant config** | MVP targets pilot users self-hosting or you hosting one instance per pilot, not multi-tenant SaaS — see PRD §10. Keeps auth/billing complexity out of the MVP critical path. |

## 3. Data Model

```
workspaces                   -- Personal | Team | Organization (IA.md §1-2)
  id, name, slug, kind

memberships                  -- RBAC: who has what role in which workspace (IA.md §3)
  id, workspace_id, user_id, role (super_admin|org_admin|team_manager|employee|guest)

connections
  id, workspace_id, provider (github), org, repo, encrypted_token, last_synced_at

signals                      -- raw, normalized facts from integrations
  id, workspace_id, connection_id, type (pr_opened|pr_merged|review_submitted|commit|issue),
  external_id, actor, payload (json), occurred_at, ingested_at
  unique (connection_id, type, external_id)   -- makes ingestion idempotent/resumable

agent_runs                   -- one LangGraph execution; the correlation id for logs/traces
  id, workspace_id, connection_id, status (running|success|partial|failed),
  triggered_by (schedule|manual), started_at, finished_at, node_errors (json), error

findings                     -- output of a specialist agent
  id, workspace_id, run_id, agent (engineering|executive|...), type,
  severity (0-1), confidence (0-1), summary, root_cause, suggested_action,
  evidence (json: signal ids / links), created_at

briefs                       -- output of the Executive Agent
  id, workspace_id, run_id, generated_at, top_finding_ids (json array of finding ids),
  narrative (text), data_freshness (json: per-agent staleness/failure notes)
```

Design intent: **signals are immutable facts, findings are agent opinions, briefs are the
synthesized opinion-of-opinions.** This three-layer split is what makes the system explainable —
you can always walk a brief → its findings → the signals that produced them.

**Every workspace-owned table carries `workspace_id`, and every read/write goes through a
`WorkspaceScopedRepository`** (`app/repositories/base.py`) bound to one workspace at construction
time — routes and agents never issue a raw query against these tables, so it is structurally
impossible to forget the tenant filter and leak data across workspaces. Phase 1 only ever
constructs one workspace and one repository scope per request, but the same repository class is
what Phase 2's real multi-tenant RBAC runs on — no rewrite, just more callers.

**`agent_runs.id` (`run_id`) and `workspace_id` are the two ids the whole observability and
security story hang off.** Every structured log line, every Finding, and every Brief carries both,
so a finding that looks wrong can be traced: log line → `run_id` → the exact LangGraph run → the
exact signals it read (see `app/core/logging.py`'s `bind_run_context`).

## 4. Agent Contract

Every specialist agent implements the same interface so the orchestrator (and future agents) can
treat them uniformly:

```python
class Agent(Protocol):
    name: str
    def gather_signals(self, since: datetime) -> list[Signal]: ...
    def analyze(self, signals: list[Signal]) -> list[Finding]: ...
```

`analyze()` is where the LLM is invoked — and it is invoked with **pre-computed metrics**, not raw
signal dumps (e.g., "p90 review time went from 4h to 19h over the last 7 days, driven by PRs
touching `auth/`" rather than a list of 400 raw PR JSON objects). This keeps token usage low and
keeps the LLM's job to what it's good at: turning a metrics summary into a root-cause narrative
with a confidence score, not doing the statistics itself.

The Executive Agent has a different contract — it consumes `list[Finding]` across all specialist
agents for the current run and produces a single `Brief`.

## 5. LangGraph Orchestration

```
StateGraph:
  nodes: engineering_agent, [project_agent, communication_agent, ...future], executive_agent
  entry: all specialist agent nodes run in parallel (fan-out)
  edge: specialist nodes → executive_agent (fan-in)
  state: { signals_by_agent, findings_by_agent, brief }
```

MVP graph has exactly two nodes (`engineering_agent → executive_agent`) but is built as an N-node
fan-out/fan-in graph from day one so Phase 2/3 agents are additive (new node + one new edge into
`executive_agent`), not a rewrite.

## 6. Integration Strategy

- **GitHub (MVP)**: REST API via a personal access token to start (simplest for pilot users to
  set up); migrate to a GitHub App (higher rate limits, installable, narrower scopes) once past
  single-repo pilots.
- **Incremental sync**: store `last_synced_at` per connection; every poll only requests data since
  that timestamp; store raw payload in `signals.payload` for full auditability without needing to
  re-fetch from GitHub.
- **No source code sent to the LLM**: the GitHub client extracts metadata (titles, timestamps,
  authors, changed file paths, additions/deletions counts, review state) and explicitly does not
  fetch diff/patch bodies. This is enforced at the client layer, not just the prompt layer.

## 7. Deployment Topology (MVP)

Local/dev: `docker-compose.yml` running MySQL, Redis, FastAPI (`uvicorn`), Celery worker,
Celery beat, and the Vite dev server.

Pilot hosting: same compose stack on a single small VM per pilot (or a shared instance with
connection-scoped data if you're comfortable with that trust boundary for friendly pilots) —
deliberately not multi-tenant infrastructure yet, per PRD scope.

## 8. Security & Observability (implemented in Phase 1, not deferred)

These were flagged as production-readiness requirements before implementation started; they're
built into the scaffold from the first commit rather than bolted on later.

- **Tenant isolation**: `WorkspaceScopedRepository` (§3) — no route or agent can query a
  workspace-owned table without going through a workspace-bound repository.
- **Credentials encrypted at rest**: `app/core/security.py` — Fernet encryption for
  `connections.encrypted_token`; the key lives only in the deployment's env/secret store.
- **Structured, correlated logging**: `app/core/logging.py` — every log line is JSON and carries
  `run_id`/`workspace_id`/`agent` via `bind_run_context`; sensitive keys (tokens, API keys) are
  redacted by a processor, not by convention.
- **Idempotent ingestion**: the `(connection_id, type, external_id)` unique constraint on `signals`
  + `INSERT ... ON DUPLICATE KEY UPDATE` means a retried poll can never duplicate data.
- **Metadata-only GitHub client**: `app/integrations/github_client.py` never requests diff/patch
  bodies — enforced in the client, not just the prompt (§6, and the LLM data boundary is treated as
  a security control, not a privacy nicety).
- **Rate-limit-aware, retrying HTTP client**: the GitHub client backs off before hitting GitHub's
  rate limit floor and retries transient failures with exponential backoff, rather than crashing
  an ingestion run.
- **Partial failure as a first-class run state**: `agent_runs.status` includes `partial`, with
  `node_errors` recording which LangGraph node failed — one agent's failure doesn't take down the
  whole brief, and the brief can say "engineering data is stale" instead of silently going quiet.

## 9. Extension Points (so Phase 2+ doesn't require rework)

- New integration = new client in `integrations/` + new row type(s) in `signals.type`.
- New specialist agent = new class implementing the `Agent` protocol + one new LangGraph node/edge.
- Cross-agent correlation (Phase 2's real novelty) = the Executive Agent's `analyze()` gains access
  to `findings_by_agent` (plural) instead of a single agent's findings — the state shape already
  supports this, so Phase 2 work is additive logic, not schema migration.
- Push delivery (email/Slack brief delivery, currently dashboard-only) = a new consumer of the
  `briefs` table; no changes to ingestion or agent logic required.
