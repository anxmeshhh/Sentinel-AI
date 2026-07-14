# Sentinel AI — Product Requirements Document

**Tagline:** "Know what's going wrong before anyone else does."
**Status:** Draft v1
**Owner:** Animesh
**Last updated:** 2026-07-14

---

## 1. Problem Statement

Every company runs on a dozen disconnected tools — GitHub, Jira, Slack, Notion, Google Docs,
Calendar, email, CRM, CI/CD, monitoring. The signals that predict a missed deadline, a burned-out
engineer, or a broken deployment all exist *somewhere* in this data — but nobody has time to sit
down every day and connect a PR review slowdown to a Slack silence to a CI failure spike. By the
time a human notices the pattern, the sprint is already blown.

The problem isn't a lack of data. It's that dot-connecting doesn't scale with headcount, and no
single person has visibility into all ten systems at once.

## 2. Vision

Sentinel is a digital COO that continuously observes a company's tools, reasons across them with
a fleet of specialized AI agents, and surfaces problems *before* anyone asks a question — not a
chatbot you query, but a system that pushes insight at you.

```
Company Tools → Continuous Observation → Specialized Agents → Reasoning →
Decision-Making → Recommended Actions (pushed, not pulled)
```

Success looks like: "Sprint Alpha has a 78% probability of missing its deadline. Root cause: API
review bottleneck. Suggested action: assign Reviewer B to the authentication module." — delivered
Thursday, before the Friday standup where a human would have first said it out loud.

## 3. Target Users

- **Engineering managers / VPs of Engineering** at 20–200 person companies — the primary buyer and
  daily user of the brief.
- **Founders/CTOs** at startups who don't have a dedicated EM and need an early-warning system.
- **Team leads** who want a defensible, data-backed answer to "why is X late?" instead of a guess.

Non-target for v1: individual contributors (no per-developer surveillance framing), enterprises
needing SSO/compliance (that's a post-PMF concern).

## 4. Product Principles

1. **Discover, don't wait to be asked.** The core loop is a push (daily/on-change brief), not a
   chat window. A chat interface may exist later as a secondary surface, never the primary one.
2. **Root cause, not raw data.** Every alert names a cause and a suggested action — never just
   "here's a metric that moved."
3. **Privacy-conscious by default, especially for people-signals.** Workload/burnout analysis
   reasons about patterns and team-level aggregates, not individual judgment calls. This is a
   binding non-negotiable for the HR/Wellbeing agent, opt-in only.
4. **Confidence over noise.** An agent that cries wolf gets muted and ignored — every finding
   carries an explicit probability/confidence score, and low-confidence findings are suppressed by
   default, not surfaced as maybes.
5. **Explainable.** Every recommendation must show its evidence trail (which PRs, which messages,
   which tickets) — never a black-box score.

## 5. Scope

### 5.1 MVP (Phase 1) — "Prove the core loop works on real data"

Two agents, one real integration, one synthesized output:

- **Engineering Agent** — ingests GitHub (PRs, commits, issues, reviews) for a connected repo.
  Detects: review-time bottlenecks, code hotspots (files with concentrated high-churn/high-defect
  activity), inactive contributors relative to their baseline, and risky deploy patterns
  (large/late/unreviewed merges to main).
- **Executive Agent** — reads the Engineering Agent's findings (and, as more agents come online,
  theirs too) and produces a daily brief: top 3 risks, ranked by severity/confidence, each with a
  root cause and a suggested action.
- **Delivery surface**: a web dashboard (not yet email/Slack push) showing the current brief and
  the evidence behind each finding.

MVP explicitly excludes: Jira/Linear, Slack, Notion, Docker/K8s monitoring, finance, HR/wellbeing,
security scanning, meeting transcripts. These are Phase 2+ (see ROADMAP.md).

**MVP success = a real engineering team can connect their GitHub org and get a brief that names a
real bottleneck they'd agree is real, within one week of signal collection.**

### 5.2 Phase 2 — Add the project + risk layer

- **Project Agent** (Jira/Linear) — sprint burndown reasoning, deadline-slip prediction. This is
  what turns "the API module is a bottleneck" into "and therefore Sprint Alpha is at risk."
- Cross-agent correlation in the Executive Agent (engineering signal + project signal → compound
  risk score), which is the first real demonstration of the "connect the dots across tools" thesis.

### 5.3 Phase 3 — Communication + Knowledge layer

- **Communication Agent** (Slack) — gaps, unanswered questions, missing approvals.
- **Knowledge Agent** (Notion/Confluence/Docs) — staleness, missing docs, duplication.

### 5.4 Phase 4 — Ops, security, finance, people

- **DevOps Agent**, **Security Agent**, **Finance Agent**, **HR Wellbeing Agent** (opt-in,
  aggregate-only), **Meeting Agent**.

Full detail and sequencing rationale lives in `ROADMAP.md`.

## 6. Functional Requirements (MVP)

| ID | Requirement |
|----|-------------|
| FR-1 | User can connect a GitHub org/repo via a personal access token or GitHub App install. |
| FR-2 | System polls GitHub on a schedule (default: every 6h) and ingests PRs, commits, issues, reviews since last sync. |
| FR-3 | Engineering Agent computes, per repo: median/p90 PR review latency (trend over time), file-level churn+defect hotspot ranking, per-contributor activity vs. their 30-day baseline, and a risky-deploy flag list. |
| FR-4 | Engineering Agent uses the LLM to turn raw metrics into a natural-language finding with a confidence score and cited evidence (PR links, commit SHAs). |
| FR-5 | Executive Agent runs after Engineering Agent completes, ranks findings by severity × confidence, and produces a brief: top risks + root cause + suggested action. |
| FR-6 | Dashboard shows: current brief, historical brief archive, and drill-down from any finding to its underlying evidence. |
| FR-7 | System stores all raw ingested signals and all agent outputs (audit trail / explainability). |
| FR-8 | A brief can be manually triggered (re-run now) in addition to the schedule. |

## 7. Non-Functional Requirements

- **Latency**: brief generation completes within 5 minutes of a manual trigger for a repo with
  <5,000 PRs of history.
- **Cost**: MVP must run on Groq's free/low tier for LLM calls; design agent prompts to minimize
  token usage (summarize before sending to LLM, don't dump raw diffs).
- **Reliability**: ingestion is idempotent and resumable (a failed poll doesn't duplicate data or
  require a full re-sync).
- **Security**: GitHub tokens encrypted at rest; no source code content is sent to the LLM, only
  metadata (titles, timestamps, authors, file paths, stats) — this is a hard constraint, not a
  nice-to-have, given customers will not want their proprietary code sent to a third-party LLM.
- **Explainability**: every number in the brief must be traceable to raw ingested rows.

## 8. Success Metrics

- **Phase 1 (MVP) exit criteria**: 3 real repos (yours + 2 pilot users/friends' companies)
  connected; each produces at least one finding the repo owner independently confirms is accurate.
- **Phase 2 exit criteria**: at least one "compound" finding (engineering + project signal
  together) that a pilot user says they would not have caught themselves, at least a day before
  they would have caught it manually.
- **North star (longer-term)**: % of surfaced findings marked "accurate" by users vs. dismissed —
  target >70% accuracy before expanding to more agents, since noise kills trust fast in this
  product category.

## 9. Risks

| Risk | Mitigation |
|------|------------|
| False positives erode trust quickly ("cried wolf") | Confidence scoring + suppression threshold; only ship high-precision findings in MVP even at the cost of recall. |
| GitHub API rate limits at scale | Use conditional requests (ETags), incremental sync, GitHub App (higher limits) over PAT once past MVP. |
| LLM cost/latency at scale (many repos × frequent polling) | Groq's inference speed helps; keep prompts metrics-based/summarized, not raw-data dumps; cache/reuse embeddings or summaries where possible. |
| Sending sensitive data to a third-party LLM | Never send source code/diff bodies — only structured metadata — documented as a hard architectural constraint. |
| Scope creep (10 agents is a lot) | Roadmap is intentionally sequential; do not start Phase 2 work until Phase 1 exit criteria are met on real data. |

## 10. Out of Scope for v1 (explicitly)

- Multi-tenant SaaS billing/auth (single-tenant / self-hosted-style config for MVP).
- Mobile app.
- Real-time streaming ingestion (polling is sufficient for MVP).
- Any agent making an autonomous *write* action (e.g., auto-reassigning a reviewer) — v1 only
  recommends; a human acts.
