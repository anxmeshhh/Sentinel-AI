# Sentinel AI — Roadmap

Sequencing is deliberate: each phase only starts once the prior phase's exit criteria (PRD §8) are
met on real data. Building all 10 agents in parallel would produce 10 shallow, untrustworthy
agents instead of 2-3 that people actually rely on.

---

## Phase 1 — MVP: Prove the Core Loop (Engineering + Executive)

**Goal:** one real repo → one real, trusted finding.

- [ ] Backend skeleton: FastAPI, Postgres, Celery/Redis, docker-compose
- [ ] GitHub integration client (PRs, commits, issues, reviews; metadata only, no code)
- [ ] Engineering Agent: review-latency trend, file hotspots, contributor activity baseline, risky-deploy flags
- [ ] LangGraph orchestrator: Engineering Agent → Executive Agent
- [ ] Executive Agent: ranks findings, produces daily brief with root cause + suggested action
- [ ] Groq LLM client (metrics-in, narrative-out; no raw data dumps)
- [ ] React dashboard: current brief, evidence drill-down, manual re-run
- [ ] Pilot on 3 repos (yours + 2 others), confirm ≥1 accurate finding each

**Estimated effort:** 2–3 weeks solo, focused.

## Phase 2 — Project Layer + Cross-Agent Correlation

**Goal:** demonstrate the actual thesis — connecting dots *across* tools, not just within GitHub.

- [ ] Project Agent: Jira and/or Linear integration, sprint burndown reasoning, deadline-slip prediction
- [ ] Executive Agent upgrade: consume multiple agents' findings, produce compound findings (e.g., engineering bottleneck + sprint velocity drop → "Sprint Alpha at risk")
- [ ] Brief delivery beyond dashboard: Slack/email push of the daily brief
- [ ] Pilot exit criteria: ≥1 compound finding a user says they wouldn't have caught themselves, ≥1 day early

**Estimated effort:** 2–3 weeks.

## Phase 3 — Communication + Knowledge Layer

- [ ] Communication Agent (Slack): gaps, unanswered questions, missing approvals
- [ ] Knowledge Agent (Notion/Confluence/Docs): staleness, missing docs, duplication
- [ ] Executive Agent incorporates both into brief ranking

**Estimated effort:** 3–4 weeks (Slack/Notion API integration + noisier signal handling).

## Phase 4 — Ops, Security, Finance, People

- [ ] DevOps Agent (Docker/K8s/logs/deploy alerts)
- [ ] Security Agent (credential leaks, dangerous commits, secret exposure)
- [ ] Finance Agent (cloud cost spikes, API usage, budget overruns)
- [ ] HR Wellbeing Agent — **opt-in only**, aggregate/team-level workload pattern signals (meeting load, context-switch frequency, response latency), explicitly no individual-level judgment output. Requires its own privacy review before shipping.
- [ ] Meeting Agent (transcripts → decisions, action items, forgotten tasks)

**Estimated effort:** largest phase, 6+ weeks — likely reprioritized based on pilot user demand
rather than built in the listed order. Whichever agent pilot users ask for first should jump the
queue.

## Beyond Phase 4

- Multi-tenant SaaS (auth, billing, org isolation) once there's pull from users beyond friendly pilots
- Autonomous *actions* (not just recommendations) — e.g., auto-opening a Jira ticket or
  reassigning a reviewer — gated behind explicit user opt-in per action type, never default-on
- GitHub App migration (from PAT) for scale and narrower permission scopes

---

## Guiding rule for sequencing

Do not start building a new agent until the current agent's findings have been validated as
accurate by a real user on real data. An unvalidated agent adds noise, and noise is the #1 way
this product category loses trust (see PRD §9 risks).
