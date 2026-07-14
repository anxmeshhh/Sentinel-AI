# Sentinel AI — Architecture & Strategy

**Status:** Draft v1, covers MVP (Phase 1) with extension points for Phases 2–4.

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
                     │                 Postgres                      │
                     │  signals | findings | briefs | connections    │
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
| **Postgres** | Findings/briefs are structured, relational, and need to be queried/joined (e.g., "all findings referencing PR #123") — not a good fit for a pure document store. JSONB columns handle the semi-structured evidence payloads. |
| **LangGraph** | The product shape *is* a graph: N specialist agents feed one synthesis agent, and Phase 2 adds cross-agent edges (Project Agent's findings modify how Executive Agent weighs Engineering Agent's findings). LangGraph models this explicitly as a graph with shared state, rather than hand-rolling orchestration logic. It's LLM-provider-agnostic, so swapping Groq for another provider later doesn't require re-architecting. |
| **Groq (Llama models via `langchain-groq`)** | Only LLM credential currently available; also a genuine fit — Groq's inference speed matters because the Executive Agent's job is to synthesize on a schedule across potentially many agents' worth of findings, and fast, cheap inference keeps that loop tight. Provider is abstracted behind a single `llm.py` client so switching to Claude/OpenAI later is a one-file change. |
| **React + Vite + Tailwind** | Standard, fast-to-build dashboard stack; no need for Next.js SSR since this is an authenticated internal dashboard, not a marketing site — Vite keeps the dev loop simple. |
| **Docker Compose (local), single-tenant config** | MVP targets pilot users self-hosting or you hosting one instance per pilot, not multi-tenant SaaS — see PRD §10. Keeps auth/billing complexity out of the MVP critical path. |

## 3. Data Model (MVP)

```
connections
  id, provider (github), org, repo, encrypted_token, last_synced_at

signals                      -- raw, normalized facts from integrations
  id, connection_id, type (pr_opened|pr_merged|review_submitted|commit|issue),
  external_id, actor, payload (jsonb), occurred_at, ingested_at

findings                     -- output of a specialist agent
  id, agent (engineering|executive|...), type, severity (0-1), confidence (0-1),
  summary, root_cause, suggested_action, evidence (jsonb: signal ids / links),
  run_id, created_at

briefs                       -- output of the Executive Agent
  id, run_id, generated_at, top_findings (ordered array of finding ids),
  narrative (text)

agent_runs
  id, started_at, finished_at, status, triggered_by (schedule|manual)
```

Design intent: **signals are immutable facts, findings are agent opinions, briefs are the
synthesized opinion-of-opinions.** This three-layer split is what makes the system explainable —
you can always walk a brief → its findings → the signals that produced them.

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

Local/dev: `docker-compose.yml` running Postgres, Redis, FastAPI (`uvicorn`), Celery worker,
Celery beat, and the Vite dev server.

Pilot hosting: same compose stack on a single small VM per pilot (or a shared instance with
connection-scoped data if you're comfortable with that trust boundary for friendly pilots) —
deliberately not multi-tenant infrastructure yet, per PRD scope.

## 8. Extension Points (so Phase 2+ doesn't require rework)

- New integration = new client in `integrations/` + new row type(s) in `signals.type`.
- New specialist agent = new class implementing the `Agent` protocol + one new LangGraph node/edge.
- Cross-agent correlation (Phase 2's real novelty) = the Executive Agent's `analyze()` gains access
  to `findings_by_agent` (plural) instead of a single agent's findings — the state shape already
  supports this, so Phase 2 work is additive logic, not schema migration.
- Push delivery (email/Slack brief delivery, currently dashboard-only) = a new consumer of the
  `briefs` table; no changes to ingestion or agent logic required.
