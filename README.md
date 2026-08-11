# Sentinel AI

**Autonomous Operations Intelligence Platform**
*"Know what's going wrong before anyone else does."*

Every company runs on a dozen disconnected tools — GitHub, Jira, Slack, Notion, CI/CD, monitoring,
finance. The signals that predict a missed deadline or a broken deployment already exist somewhere
in that data; nobody has time to connect the dots. Sentinel is a digital COO that continuously
observes those tools, reasons across them with a fleet of specialized AI agents, and pushes a
daily brief that names the risk, the root cause, and a suggested action — before a human would
have noticed the pattern.

```
Company Tools → Continuous Observation → Specialized Agents → Reasoning →
Decision-Making → Recommended Actions (pushed, not pulled)
```

This is not a chatbot. There is no query box as the primary interface — Sentinel tells you what's
wrong, it doesn't wait to be asked.

## Status

**Building.** The pipeline runs end to end on real accounts:

```
Connectors → Signals → Findings → Entities → Situations
          → Context → Reasoning → Memory → Decisions → Action Registry
```

- **12 connected services** across five provider families — Google (Gmail,
  Calendar, Drive), GitHub, Slack, Microsoft 365 (Outlook Mail, Outlook
  Calendar, Teams, OneDrive, OneNote, To Do) and Zoom. Each was live-verified
  against a real account before being called done.
- **Deterministic detection, LLM narration.** Findings come from rules; the LLM
  only ever sees `SituationContext.to_facts()` and never invents a finding.
- **Every write goes through the Action Registry** — allow-listed, previewed,
  confirmed, executed, verified against the provider, audited, and undone where
  a real inverse exists.
- **808 backend tests.**

Honest gaps: correlation has not yet fired on real data (no two findings have
shared an entity), so Reasoning/Memory/Decisions run only in tests; Notion and
Jira are not started.

## Documentation

| Doc | Contents |
|-----|----------|
| [`PRD.md`](./PRD.md) | Problem statement, vision, target users, MVP scope, functional/non-functional requirements, success metrics, risks |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | System design, tech stack rationale, data model, agent contract, LangGraph orchestration, deployment topology |
| [`CONNECTIONS.md`](./CONNECTIONS.md) | Per-provider setup: OAuth apps, scopes, redirect URLs, plan limits, and the traps each provider has |
| [`ROADMAP.md`](./ROADMAP.md) | Phased build plan from MVP to the full 10-agent platform |

## The 10 Agents (Vision)

| # | Agent | Reads | Finds |
|---|-------|-------|-------|
| 1 | Engineering | GitHub (PRs, commits, issues) | Bottlenecks, code hotspots, inactive devs, risky deploys |
| 2 | Meeting | Transcripts (Meet, Zoom) | Decisions, action items, forgotten tasks |
| 3 | Project | Jira, Trello, Linear | Sprint failure risk, deadline slips |
| 4 | Communication | Slack, Discord, Teams | Communication gaps, confusion, missing approvals |
| 5 | Knowledge | Notion, Confluence, Docs | Outdated/missing docs, duplicate knowledge |
| 6 | Security | Commits, config | Credential leaks, dangerous commits, secret exposure |
| 7 | DevOps | Docker, Kubernetes, logs, deploys | Deployment risk, alerts |
| 8 | HR Wellbeing *(opt-in)* | Workload patterns | Burnout signals, meeting overload — team-level only, never individual judgment |
| 9 | Finance | Cloud billing, API usage | Unexpected cost spikes, budget overruns |
| 10 | Executive | Every other agent's findings | Daily brief: priorities, risks, recommendations |

Building all 10 at once produces 10 shallow, untrusted agents. Sentinel ships them sequentially —
see `ROADMAP.md` for the phase order and exit criteria that gate moving to the next agent.

## MVP Scope (Phase 1)

Two agents prove the core loop before anything else is built:

- **Engineering Agent** — ingests a connected GitHub repo, detects review-latency bottlenecks,
  file hotspots, inactive contributors, and risky deploys.
- **Executive Agent** — synthesizes those findings into a ranked daily brief with root cause and
  suggested action.

Full detail in `PRD.md` §5.1 and `ROADMAP.md` Phase 1.

## Tech Stack

- **Backend**: Python, FastAPI, Celery + Redis (scheduled ingestion/agent runs)
- **Database**: Postgres
- **Agent orchestration**: LangGraph (specialist agents fan into the Executive Agent)
- **LLM**: Groq (Llama models), abstracted behind a single client so the provider can change later
- **Frontend**: React + Vite + Tailwind

Rationale for each choice is in `ARCHITECTURE.md` §2.

## Guiding Principles

1. Discover, don't wait to be asked — push, not pull.
2. Root cause, not raw data — every finding names a cause and a suggested action.
3. Privacy-conscious by default — people-signal agents (HR Wellbeing) are opt-in, aggregate-only,
   never individual judgment.
4. Confidence over noise — low-confidence findings are suppressed, not surfaced as maybes.
5. Explainable — every finding traces back to the raw evidence that produced it.

## License

See [`LICENSE`](./LICENSE).
