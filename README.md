# Sentinel AI

**Operations intelligence over the tools you already use.**

Work happens across a dozen disconnected services. The signals that predict a
missed deadline, a stalled review or a dropped conversation already exist in
that data — nobody has time to connect them. Sentinel watches the services you
connect, correlates what it finds, and tells you what needs you and why.

```
Providers → Signals → Findings → Entities → Situations
         → Context → Reasoning → Memory → Decisions → Goals
         → Assistant → Action Registry
```

One pipeline. Every domain flows through it; there is no second engine for any
provider or feature.

---

## The one rule that shapes everything

**Detection is deterministic. The model only ever narrates.**

Severity, priority, progress, goal health and risk are computed in Python from
stored data, and every one of them writes a plain-language reason a person can
check. The LLM is given the conclusion and asked to phrase it — it is never
asked to decide it, and it never sees raw provider data.

The reason is practical: a confident "73% complete" nobody can trace is worse
than no number, and a launch declared on-track by a model that skimmed some
text is worse still.

---

## What is implemented

### Intelligence Core

| Stage | What it does | LLM |
|---|---|---|
| **Signals** | Normalized provider events (12 types) | none |
| **Findings** | One canonical read model over attention items and situations | none |
| **Entities** | Repos, channels, services, people extracted from findings | none |
| **Situations** | Findings about the *same* entity correlated across providers | none |
| **Context** | The evidence package a situation is built from | none |
| **Reasoning** | Deterministic priority + recommended actions | 1, gated on change |
| **Memory** | Patterns that recurred, with decay and undo | none |
| **Decisions** | Confirm-first proposals grounded in a situation | none |
| **Goals** | Health/progress computed from linked commitments | 1, gated on change |

Every LLM step is fingerprint-gated: a situation whose evidence has not changed
is never re-narrated.

### Detection — 22 deterministic detectors

**19 attention detectors** and **3 proactive detectors**, producing 20 attention
types. All are arithmetic over stored payloads — no LLM anywhere in detection.

| Domain | Detectors |
|---|---|
| Meetings | upcoming meeting, unprepared meeting, **conflict/double-booking**, **weekly overload** |
| Engineering | stale PR, stalled resource, **slow merge**, **review bottleneck**, **bus factor**, **stale issue** |
| Communication | important email, unanswered mail, mention, blocker, urgent burst, **thread stall** |
| Projects | deadline, overdue task, task due today, commitments |
| Knowledge | **stale shared document** |
| Executive | service jeopardy, workspace verdict, **week-over-week trends** |

**Bold** = built in the existing-data intelligence pass, from signals that were
already being ingested. Two of them read data that had never been looked at:
issues had been ingested since the GitHub module shipped with no detector at
all, and `changed_dirs` was fetched on every PR and used for nothing.

### Agentic Assistant

The primary interface. A deterministic router maps a message to an existing
capability; nothing in it decides what matters.

```
OBSERVE → UNDERSTAND → PLAN → CONFIRM → ACT → VERIFY → REPORT
```

- **Three dimensions**, all resolved before data is read: **scope** (Personal
  or one group, chosen explicitly — never inferred from wording), **provider**
  (detected deterministically, applied as a filter over Core data), **intent**
  (regex, no model).
- **Zero LLM** for: attention, findings, situations, goals, decisions, status,
  memory, investigate, search, provider questions, and acting on a target.
- **At most one** for: catch-up, meeting prep, turning prose into an action
  proposal, and the grounded fallback. The budget is declared per intent in a
  table that is exhaustive over the intent type and asserted at runtime.
- Measured: **4 LLM calls across 17 representative questions.**

Target resolution is deterministic — "this" is the last thing shown, "the
deployment issue" is matched against it. Two candidates produce a pick-list,
never a ranked guess.

### Action Registry — the only execution layer

**40 actions, 38 available.** Every available one has a verifier; 32 have a
real undo.

```
propose → validate → authorize → preview → confirm → execute → verify → audit
```

- Parameters from a model are untrusted input: validated by Pydantic, then
  re-validated against the scope at execution.
- Risk escalates on parameters — a calendar event for yourself is a private
  write; the same event with attendees is an invitation to other people, and is
  priced as one.
- `SUCCEEDED` means executed **and confirmed**. `UNKNOWN` exists so nobody is
  told to retry something that may already exist.
- Actions with no genuine inverse are marked irreversible rather than offered
  an undo button that cannot work.
- Nothing runs unattended. The autonomy gate is built and tested; no action
  passes it today.

### Personal vs Group

```
PERSONAL                          GROUP
├── the user's own connections     ├── connections shared to it
├── personal intelligence          ├── group intelligence
└── personal Assistant scope       └── group Assistant scope
```

`Scope` is the universal parameter of the Core. An engine only ever sees
`scope.connection_ids`, so a group scope **structurally cannot** read personal
data. Connecting a service shares it nowhere by itself.

Sentinel may combine authorized personal availability with group data to make a
better decision, and the guarantee that it does not disclose the private half
is structural rather than promised: `free_slots_for_availability` returns
`{start, end, minutes}` and nothing else, so it can say *"3 PM is unavailable"*
and physically cannot say whose appointment it is.

### Providers — 12 connected services

Google (Gmail, Calendar, Drive) · GitHub · Slack · Microsoft 365 (Outlook Mail,
Outlook Calendar, Teams, OneDrive, OneNote, To Do) · Zoom.

Each has a provider workspace with Overview, Services, Insights, Activity and
Settings. Google, GitHub and Microsoft additionally have a live provider AI
panel; the global Assistant links to those rather than proxying them, because
their tool-calling loop is multi-step by design and wrapping it would break the
one-call budget.

### Sync

- Scheduled poll (6h; Slack every 5 min), fanned out per connection.
- **Sync Now** runs the same pipeline synchronously and returns when it is
  actually done — no fake progress.
- The legacy agent pass is gated on new signals arriving, so a quiet workspace
  costs nothing.

---

## Limited

- **Detector thresholds are reasoned, not measured.** 3 days for a stalled
  thread, 20h/week for meeting overload, 4 PRs for a review queue, 21/90 days
  for stale issues and documents. Expect tuning against real volume.
- **Trends cover two weeks only.** There is no longer-range series, and no
  "resolved this week" measure: attention items carry `created_at` and nothing
  records *when* one moved to done, so that number would report when items were
  raised while claiming otherwise.
- **Commitment extraction from prose is unvalidated on real data.** The
  pipeline is gated hard (measured: 2 of 40 message bodies would reach the
  model) but has never extracted a genuine commitment from a real mailbox.
- **Channel memory and decisions are readable but not manageable.** Forgetting
  and confirming stay personal-only; who may retire shared state is a separate
  decision.
- **Teams, SharePoint and Planner** need a licensed Microsoft work/school
  tenant. Graph refuses them on a personal account regardless of scopes.
- **Mail sending** is registered but unavailable — the one action whose test
  cannot be cleaned up afterwards.
- **Legacy agent pipeline.** Four LLM detectors remain (contributor drop, risky
  deploy, stale flagged mail, spam surge). Two others were retired once
  deterministic equivalents existed.

## Not implemented

Four domains are blocked on data that is not ingested, not on effort:

| Domain | Missing |
|---|---|
| **Security** | No vulnerability, dependency, secret-scanning or audit-log ingestion |
| **DevOps** | **No CI data at all** — no workflow runs, checks or deployments. "deploy" exists only as a chat keyword |
| **Finance** | No financial data source of any kind |
| **HR Wellbeing** | Calendar timestamps could weakly proxy workload, but the model is opt-in and team-level only, and no consent mechanism exists. Blocked on consent design, not data |

Building these means adding ingestion first. Nothing in the UI pretends they
exist.

---

## LLM usage

- **Provider:** Groq. Model: `openai/gpt-oss-120b`, behind a single client so it
  can be swapped in one file.
- **20 call sites**, all narration, explanation or NLU. None in detection.
- Every background narration is fingerprint-gated. A workspace where nothing
  changed costs nothing.
- The Assistant's budget is enforced by a table exhaustive over its intent type,
  so a new intent cannot be added without choosing a budget.

## Security & privacy

- Scope is derived server-side and never accepted as a parameter.
- Reads and writes use the same ownership rule, stated once — a write can never
  be authorized more loosely than the read that revealed the item.
- Fail-closed throughout: an item whose provenance cannot be established is
  visible and writable to nobody.
- Tokens are Fernet-encrypted at rest, never logged, never serialized.
- Message bodies are fetched live and discarded, never stored.
- Every action records who requested it, who approved it, what they were shown,
  and what the provider confirmed.

## Testing

**902 backend tests across 70 files.** Frontend: TypeScript strict + production
build.

Privacy tests are written from the attacker's side and include executable
proofs of the old behaviour — a test asserts that an unscoped calendar read
*would* have returned another member's private event, so the filter cannot be
reasoned away as redundant later.

## Stack

- **Backend:** Python, FastAPI, Celery + Redis
- **Database:** MySQL (SQLAlchemy + Alembic)
- **Frontend:** React + Vite + Tailwind
- **LLM:** Groq, single-client abstraction

## Documentation

| Doc | Contents |
|-----|----------|
| [`PRD.md`](./PRD.md) | Problem, vision, users, scope, requirements |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | System design, data model, orchestration |
| [`CONNECTIONS.md`](./CONNECTIONS.md) | Per-provider OAuth setup, scopes, traps |
| [`ROADMAP.md`](./ROADMAP.md) | Phase order and exit criteria |

## Roadmap

1. Validate detector thresholds against real volume.
2. A resolution timestamp, unlocking throughput and time-to-resolve.
3. CI ingestion — the single highest-value addition, unblocking DevOps and part
   of Security.
4. Consent design for team-level wellbeing, before any inference is attempted.
5. Longer-range trends now that history accumulates.

## Principles

1. **Deterministic first.** If it can be computed, it is not inferred.
2. **Explainable.** Every verdict carries reasons that trace to real rows.
3. **Confirm before acting.** Nothing external happens without a person.
4. **Fail closed.** Provenance that cannot be established is not assumed.
5. **Say what is true.** A missing capability is reported, never approximated.

## License

See [`LICENSE`](./LICENSE).
