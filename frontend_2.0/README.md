# Sentinel Insights

SENTINEL — FRONTEND SPECIFICATION

Paste this whole document into Lovable.

---
0. WHAT SENTINEL IS

Sentinel is an operational intelligence workspace. It connects to the tools a person already works in (Google, Microsoft 365, GitHub, Slack, Zoom), notices what actually needs attention, explains why things are connected, remembers what keeps happening, and lets the user act — without leaving Sentinel.

It is not an integration dashboard. Connections are plumbing, shown once and then forgotten. The product is the intelligence.

The core loop the UI must make visible

Signals → Findings → Entities → Situations → Context → Reasoning → Memory → Decisions → Actions
 (raw)    (matters)  (about)    (related)    (evidence) (why)      (learned) (suggested) (done)

The user must be able to follow this chain without ever learning those words as jargon. Achieve it through layout and copy, not labels: a Situation shows its Findings, each Finding shows its evidence, each evidence item links to the real thing in the real provider.

Design principles

Calm · Professional · Modern · Intelligent · Minimal · Information-dense without clutter · Strong hierarchy · Trustworthy · Human, not "AI gimmicky"

Explicitly avoid: generic SaaS dashboards, cards nested in cards, a giant chat window as the main UI, fake analytics/charts, decorative AI animations, glow effects, per-provider visual styling that breaks consistency.

---
1. DESIGN SYSTEM

1.1 Colour — near-monochrome, hue reserved for status

Dark is the primary theme. Hierarchy comes from surface elevation and ink contrast, not colour.

BACKGROUND / SURFACES
ground          #000000   page background
surface         #0A0A0A   panels
surface-2       #141414   cards on panels
surface-3       #1E1E1E   raised / hover
border          #2E2E2E   edges
border-strong   #454545   emphasised edges
rule            #1A1A1A   hairline structural grid (dimmer than border)

INK  (contrast-checked; never go below these)
ink             #F5F5F5   body + headings      ~17:1
ink-dim         #B0B0B0   secondary text       ~8.9:1
ink-faint       #8C8C8C   labels + metadata    ~5.3:1

SEVERITY / STATUS — the only saturated colour in the product
crit            #F0736A   critical
warn            #E8B25E   review / caution
watch           #7FA3E0   informational / syncing
good            #5FBF87   healthy / done

ACCENT — deliberately not a hue
accent          #EDEDED   primary button fill (light pill on dark)
accent-ink      #000000   text on accent fill

BRAND — punctuation only, never on controls
brand           #C9A06B   eyebrow labels, active-position bar, featured tint

CONTEXT IDENTITY — low opacity only (badges, thin borders). Never a page fill.
ctx-personal    #6FC3E8   private to you
ctx-org         #9A8FE6   shared workspace
ctx-class       #C9A06B   shared class

Rules:
- Colour never carries meaning alone. Always pair with an icon and a word.
- Severity hues appear as small dots, thin left borders, or text — never as filled backgrounds on large areas.
- No gradients. No glows. No coloured buttons.

1.2 Typography — one family, hierarchy from size and weight

micro     12.5px / 1.45 / +0.01em   labels, metadata
caption   13.5px / 1.5              secondary UI text
small     14.5px / 1.55             list rows, dense content
body      15.5px / 1.6              reading text
lead      17px   / 1.55             card titles
sub       18px   / 1.5              section headings
title     clamp(18px, 2.2vw, 20px)  panel titles
h3        clamp(20px, 3.2vw, 24px)
h2        clamp(23px, 4.2vw, 29px)  page titles
h1        clamp(28px, 5.6vw, 36px)  Command Center greeting

System sans stack (-apple-system, BlinkMacSystemFont, Inter, Segoe UI, …). Monospace only for identifiers, IDs, and counts in tables.

Display sizes are fluid (clamp) so headings are responsive with zero breakpoint classes. Body sizes stay fixed — they're already at comfortable reading size.

Never go below 12.5px anywhere.

1.3 Shape, elevation, motion

- Radius: 3–4px on cards/inputs/buttons; 6px large panels; 8px modals. Near-square, not rounded.
- Elevation: flat. Separation comes from the border alone. box-shadow: none on all cards. Only true overlays (modals, popovers, command palette) get a shadow: 0 24px 60px -12px rgba(0,0,0,0.9).
- Motion: cubic-bezier(0.22, 1, 0.36, 1), 120–180ms. Opacity and 2–4px translate only. No spring, no bounce, no pulsing "AI thinking" effects.

1.4 Spacing

4px base. Page gutters 24px desktop / 16px mobile. Card padding 16–20px. Section gaps 24px. Related items 8–12px apart.

1.5 Core components

Card — bg-surface-2, border border-border, radius 4, padding 16–20. No shadow. Optional 2px left border in a severity hue when it represents something with severity.

List row — full-width, 10–12px vertical padding, hairline divide-y divide-border. Hover bg-surface/60. Selected bg-surface/70. Rows are buttons; the whole row is the hit target.

Table — for dense records only (action audit, history). Sticky header, micro uppercase ink-faint headers with +0.06em tracking. Numeric columns right-aligned and monospace. Zebra striping is banned — use hairlines.

Status pill — micro, uppercase, 2px radius, transparent background, 1px border in the status hue, text in the same hue. Never a filled badge.

Severity dot — 6px circle in the severity hue, with the word beside it.

Buttons
- Primary — bg-accent, text-accent-ink, radius 4. One per view maximum.
- Secondary — transparent, border border-border, text-ink-dim; hover border-border-strong, text-ink.
- Ghost — text only, ink-faint → ink on hover.
- Destructive — border-crit/50, text-crit; never a filled red button except inside a confirmed irreversible flow.

Modal — centred, max-width 560px, bg-surface-2, border, overlay shadow, backdrop rgba(0,0,0,0.72). Escape and backdrop-click close. Never nest modals.

Toast — bottom-right, max-width 400px, bg-surface-3, border, auto-dismiss 6s (memory toasts 10s). Stack max 3. Always dismissible.

1.6 Universal states

Loading — skeleton blocks matching final layout (bg-surface-2, subtle opacity pulse 1.5s). Never spinners for content. Never a full-page loader after first paint.

Empty — centred within its container, dashed 1px border, border-border, generous padding. One small line of plain language + one caption line of explanation + at most one action. Never illustrations or mascots.

Error — inline, never a modal. caption in crit, stating what failed and what to do. Retry button where retry is meaningful.

Not connected — dashed container, explains what connecting enables, single primary "Connect" button.

Light mode — optional, ship dark first. If built, invert the surface ramp and ink ramp; severity hues stay identical (they're already contrast-safe on both).

---
2. TERMINOLOGY — USE EXACTLY THESE WORDS

┌───────────┬──────────────────────────────────────────────────────────────────┬────────────────────────────────┐
│  Concept  │                         User-facing term                         │           Never say            │
├───────────┼──────────────────────────────────────────────────────────────────┼────────────────────────────────┤
│ Finding   │ Finding, or "needs attention"                                    │ alert, ticket, issue           │
├───────────┼──────────────────────────────────────────────────────────────────┼────────────────────────────────┤
│ Entity    │ the repository / channel / service / person (name it concretely) │ entity, node                   │
├───────────┼──────────────────────────────────────────────────────────────────┼────────────────────────────────┤
│ Situation │ Situation                                                        │ incident, cluster, correlation │
├───────────┼──────────────────────────────────────────────────────────────────┼────────────────────────────────┤
│ Reasoning │ Why this matters                                                 │ AI analysis, LLM output        │
├───────────┼──────────────────────────────────────────────────────────────────┼────────────────────────────────┤
│ Memory    │ Sentinel remembers                                               │ ML model, learning             │
├───────────┼──────────────────────────────────────────────────────────────────┼────────────────────────────────┤
│ Decision  │ Suggested / Recommended                                          │ AI decision, automation        │
├───────────┼──────────────────────────────────────────────────────────────────┼────────────────────────────────┤
│ Action    │ Action                                                           │ command, tool call             │
├───────────┼──────────────────────────────────────────────────────────────────┼────────────────────────────────┤
│ Signal    │ (rarely shown) activity                                          │ signal, event, telemetry       │
├───────────┼──────────────────────────────────────────────────────────────────┼────────────────────────────────┤
│ Scope     │ Personal / workspace or channel name                             │ scope, tenant                  │
├───────────┼──────────────────────────────────────────────────────────────────┼────────────────────────────────┤
│ Provider  │ the product's real name (Gmail, Zoom…)                           │ integration, connector         │
└───────────┴──────────────────────────────────────────────────────────────────┴────────────────────────────────┘

Severity ladder (one vocabulary everywhere):
Critical → Review → Reminder

Voice: plain, factual, specific. Say "3 important messages have been unread for over 14 days", not "You have unread email". Never exclamation marks. Never "AI-powered". Never anthropomorphise beyond the deliberate "Sentinel remembers".

---
3. GLOBAL APP STRUCTURE

3.1 Shell layout (desktop ≥1280px)

┌──────────────────────────────────────────────────────────────────────────┐
│ TOP BAR  56px                                                            │
│  [Sentinel]   [Context switcher ▾]        [⌘K Search]  [🔔]  [Avatar ▾]  │
├────────────┬─────────────────────────────────────────────────────────────┤
│ SIDEBAR    │  MAIN                                                       │
│ 240px      │  max-width 1200px, centred, 24px gutters                    │
│            │                                                             │
│ Command    │                                                             │
│ Situations │                                                             │
│ Findings   │                                                             │
│ ─────────  │                                                             │
│ WORKSPACES │                                                             │
│  Gmail     │                                                             │
│  Calendar  │                                                             │
│  GitHub    │                                                             │
│  …         │                                                             │
│ ─────────  │                                                             │
│ Memory     │                                                             │
│ History    │                                                             │
│ ─────────  │                                                             │
│ Connections│                                                             │
│ Settings   │                                                             │
└────────────┴─────────────────────────────────────────────────────────────┘

Sidebar: bg-surface, right border border-border. Items are small, ink-dim, 8px radius, 8px/12px padding. Active item: bg-surface-2, text-ink, plus a 2px brand left bar. Section labels are micro uppercase ink-faint with +0.06em tracking.

Counts appear as right-aligned micro numerals in ink-faint — except critical counts, which are crit. Never red circle badges.

3.2 Context switcher — Personal vs Workspace vs Channel

This is Sentinel's most important structural idea and must be unmistakable.

Top bar control showing a context dot (ctx-personal / ctx-org / ctx-class), an icon, and the name:

[ ● Personal ▾ ]        or        [ ● Acme Corporation ▾ ]

Dropdown groups:
- Personal — "Only you can see this"
- Workspaces — each org, with member count
- Channels — teams within the active workspace

Rules:
- Switching context re-fetches everything. Sidebar and Command Center reflect the new context entirely.
- The context dot appears on any surface where confusion is possible.
- Personal context shows a subtle ctx-personal 1px top border on the main region — a persistent, quiet reminder that this data is private.
- Never show data from two contexts in one list.

3.3 Navigation map

/                        Command Center
/situations              Situations list
/situations/:id          Situation detail
/findings                Findings list
/findings/:id            Finding detail
/workspace/:service      Provider Workspace (gmail, google_calendar, github,
                           slack, zoom, microsoft_mail, microsoft_calendar,
                           microsoft_todo, microsoft_onedrive, microsoft_onenote,
                           microsoft_teams)
/memory                  What Sentinel remembers
/history                 Activity + action audit
/connections             Connection management
/connections/:provider   Provider connection detail
/settings                Settings

3.4 Notifications

Bell icon in the top bar. Dot indicator in brand when unread (not red — these are rarely urgent).

Panel (360px, right-anchored, max-height 480px) lists, newest first:
- New memory — 🧠 "Sentinel will remember that…"
- New Situation formed
- Critical finding appeared
- Connection needs reconnecting
- Action completed / failed

Each row: icon, one line of small text, relative timestamp in micro ink-faint. Click navigates to the subject. "Mark all read" as a ghost button in the header.

---
4. COMMAND CENTER  /

The main experience. It answers one question: what should I do right now?

4.1 Layout

┌────────────────────────────────────────────────┬──────────────────┐
│ Good morning, Animesh                      h1  │  RECENT ACTIVITY │
│ 2 things need attention · synced 4m ago  caption│                  │
│                                                │  ● Zoom synced   │
│ ┌─ SITUATIONS ────────────────────────────────┐│    4m ago        │
│ │ ● heartbeat-harmony                         ││  ● Task created  │
│ │   4 related findings · Outlook, Zoom, To Do ││    12m ago       │
│ │   "Critical upcoming meetings and an over…" ││                  │
│ │   → Prepare for the upcoming meeting        ││  ────────────    │
│ └─────────────────────────────────────────────┘│                  │
│                                                │  MEMORY          │
│ ┌─ NEEDS ATTENTION ───────────────────────────┐│  🧠 Sentinel     │
│ │ ● Critical  3 important messages unread     ││  remembers 2     │
│ │ ● Review    heartbeat-harmony has gone quiet││  things          │
│ │ ● Review    QueryMind has been paused       ││                  │
│ └─────────────────────────────────────────────┘│                  │
│                                                │                  │
│ ┌─ SUGGESTED ─────────────────────────────────┐│                  │
│ │ Review the overdue rollback task            ││                  │
│ │ Because this keeps recurring · Confirm      ││                  │
│ └─────────────────────────────────────────────┘│                  │
└────────────────────────────────────────────────┴──────────────────┘

Main column flexible; right rail 320px fixed. Rail collapses below the main column under 1024px.

4.2 Priority hierarchy — strict order, top to bottom

1. Situations — the highest-value output. Always first when any exist.
2. Needs attention — Findings, sorted Critical → Review → Reminder.
3. Suggested — Decisions, only those requires_confirmation or memory-informed.

Never reorder. Never mix. If Situations is empty, Needs Attention moves up and the Situations section disappears entirely (no empty card).

4.3 Header

- h1 greeting: "Good morning/afternoon/evening, {first name}"
- caption ink-dim summary line: "2 things need attention · synced 4m ago"
  - When nothing needs attention: "Nothing needs your attention · synced 4m ago"
  - Sync time from the most recent connection sync across the context.

4.4 Situation card

- 2px left border in the severity hue
- Title: entity display name, lead weight-500 (e.g. heartbeat-harmony)
- Meta line caption ink-faint: 4 related findings · Outlook Calendar, Zoom, Microsoft To Do
- Reasoning, 2 lines max, small ink-dim, text-balance, ellipsised
- Up to 2 recommendations as caption ink-faint prefixed →
- Entire card clickable → /situations/:id

Show at most 3; "View all N situations" ghost link below.

4.5 Needs attention

Grouped by severity with micro uppercase headers. Each row:
- 6px severity dot
- Title small ink
- Why line caption ink-faint, single line, ellipsised
- Provider name, right-aligned micro ink-faint
- Hover reveals Snooze and Done ghost actions on the right

Show 6; "View all" below.

4.6 Suggested (Decisions)

Only decisions worth a person's time. Each:
- Action text, small ink
- Rationale caption ink-faint — plain language, e.g. "Because this keeps recurring"
- If memory_informed: small 🧠 glyph before the rationale
- Confirm (secondary) and Dismiss (ghost)
- kind: recommend shows a Confirm that opens the Action confirmation flow (§9)
- kind: inform shows only Got it, which dismisses

4.7 Right rail

Recent activity — last 5 syncs/actions, one line each, caption. Purely reassurance that Sentinel is alive. No charts.

Memory — count + link to /memory. If a memory was created in the last 24h, show its summary line.

4.8 Empty states

Nothing needs attention (the good case — make it feel earned, not broken):

▎ You're clear.
▎ Sentinel is watching 12 services and nothing needs your attention right now.
▎ [ Review what Sentinel is watching ]

No connections yet (first run):

▎ Connect your first tool.
▎ Sentinel reads what you already use and tells you what actually needs attention.
▎ [ Connect a tool ]

Still syncing:

▎ Sentinel is reading your accounts.
▎ This usually takes a minute or two. Findings appear as they're detected.

4.9 Data

GET /attention · GET /decisions · GET /memory · GET /memory/announcements · GET /attention/status
Needs a new endpoint: a context-wide Situations list (currently only exposed per-service via /workspace/{service}/intelligence).

---
5. SITUATIONS

5.1 List  /situations

Header: h2 "Situations" + caption ink-dim "Related findings Sentinel connected to the same thing."

Filters (ghost pills): All · Critical · Review · Open · Resolved

Rows: severity dot · entity name (small ink) · member count + providers (caption ink-faint) · cross-provider marker · last-activity relative time, right-aligned.

Empty:

▎ No situations right now.
▎ A Situation forms when Sentinel finds two or more related things about the same repository, channel, or service.

That copy is important — it teaches the concept at the moment of absence.

5.2 Detail  /situations/:id

The most important page in the product. It must answer, in order: what happened · why are these connected · what's the evidence · what should I do.

┌─────────────────────────────────────────────┬─────────────────┐
│ ← Situations                                │  RELATED        │
│                                             │                 │
│ ● Critical                                  │  Entities       │
│ heartbeat-harmony                       h2  │   repo          │
│ 4 related findings · 3 services · opened 2h │   heartbeat-…   │
│                                             │                 │
│ WHY THIS MATTERS                            │  Providers      │
│ Critical upcoming meetings and an overdue   │   Outlook       │
│ rollback task for the heartbeat-harmony     │   Zoom          │
│ deployment are scheduled across Outlook,    │   To Do         │
│ Todo and Zoom, and the repository has shown │                 │
│ no recent activity.                    body │  Memory         │
│                                             │  🧠 Seen 2 times│
│ WHY SENTINEL CONNECTED THESE                │                 │
│ All four concern the same repository,       │                 │
│ heartbeat-harmony.                  caption │                 │
│                                             │                 │
│ FINDINGS (4)                                │                 │
│ ┌─────────────────────────────────────────┐ │                 │
│ │ ● Critical · Outlook Calendar           │ │                 │
│ │ STRESS-TEST: deployment review          │ │                 │
│ │ Starts in 3h · has a join link          │ │                 │
│ │ Open in Outlook ↗                       │ │                 │
│ └─────────────────────────────────────────┘ │                 │
│ …                                           │                 │
│                                             │                 │
│ TIMELINE                                    │                 │
│ 14 Aug 13:27  Repository went quiet         │                 │
│ 14 Aug 15:27  Deployment review scheduled   │                 │
│                                             │                 │
│ RECOMMENDED                                 │                 │
│ → Prepare for the upcoming meeting          │                 │
│   [ Confirm ]  [ Dismiss ]                  │                 │
│                                             │                 │
│ ACTIONS TAKEN                               │                 │
│ ✓ Task created in To Do · 12m ago · Undo    │                 │
└─────────────────────────────────────────────┴─────────────────┘

Section rules:

- "Why this matters" — the reasoning explanation, body, max-width 68ch. This is LLM prose but must never be labelled as such.
- "Why Sentinel connected these" — a deterministic one-liner naming the shared entity. This is the trust anchor: it proves the connection is a fact, not a guess. Generate from data, never from the LLM: "All four concern the same repository, heartbeat-harmony."
- Findings — each a card with severity, provider, title, why-line, and a direct link to the real item at the provider (Open in Outlook ↗). This is the traceability the user must be able to follow all the way down.
- Timeline — chronological, caption, hairline-separated. Time on the left in monospace micro.
- Recommended — decisions for this situation. Same interaction as §4.6.
- Actions taken — actions whose source was this situation: what ran, when, verification result, and Undo only if genuinely undoable (§9).
- Right rail — entities, providers, memory. Never duplicates the main column.

Resolved situations show a good "Resolved" pill and a muted header, with a line: "Resolved 3 days ago. Sentinel will tell you if it comes back."

Data: needs new endpoints — GET /situations, GET /situations/:id (all underlying data exists: Situation, SituationFinding, SituationReasoning, Memory, Decision).

---
6. FINDINGS

6.1 List  /findings

Header h2 "Findings" + caption "Everything Sentinel thinks is worth your attention."

Filters: severity · status (Open / Snoozed / Resolved) · provider · "In a situation" toggle.

Dense list rows:

● Critical   3 important messages are still unread          Gmail      2d
             Unread and flagged important for over 14 days
             ↳ part of a situation

- Severity dot + word
- Title small ink
- Why line caption ink-faint
- Provider + relative time right-aligned micro
- If in a situation, a ↳ part of a situation link in watch

Row hover reveals Snooze / Done / Open ↗.

Empty: "Nothing needs your attention. Sentinel is watching 12 services."

6.2 Detail  /findings/:id

- Severity + status pill
- Title h3
- Why line body ink-dim
- Evidence — the underlying activity: what, when, and a link to the real item. Metadata only, never content Sentinel doesn't hold.
- About — the entity this concerns, linked
- Source — provider + connection identity + when it was detected
- Situation — if a member, a card linking to it, explaining "Sentinel connected this with 3 other findings about heartbeat-harmony."
- Actions — snooze / mark done / provider-specific actions from the Action Registry
- History — state changes with timestamps

Data: GET /findings/:id ✅ exists.

---
7. PROVIDER WORKSPACE

One shell, every provider. A user who learns one provider page has learned them all. Provider identity comes only from the icon, the name, and the shape of the data — never from layout, colour, or interaction patterns.

7.1 Shell

┌──────────────────────────────────────────┬──────────────────┐
│ ← Microsoft 365 › Outlook Mail    (crumb)│                  │
│                                          │  INTELLIGENCE    │
│ [icon] Outlook Mail                  h2  │  RAIL            │
│ ● Connected · you@example.com · synced 4m│                  │
│                        [Quick actions →] │  (see §8)        │
│ ──────────────────────────────────────── │                  │
│                                          │                  │
│ [Filters]              [Search…]         │  ──────────────  │
│                                          │                  │
│ ┌──────────────┬─────────────────────┐   │  ASSISTANT       │
│ │ LIST         │ DETAIL              │   │  (see §9)        │
│ │              │                     │   │                  │
│ │ row          │ title               │   │                  │
│ │ row  ←sel    │ metadata            │   │                  │
│ │ row          │ [actions]           │   │                  │
│ │ row          │ content             │   │                  │
│ └──────────────┴─────────────────────┘   │                  │
└──────────────────────────────────────────┴──────────────────┘

Main flexible, rail 360px fixed. Rail moves below main under 1280px.

7.2 Service header — identical for every provider

- 44px icon tile, bg-surface-2, radius 4
- Service name h2
- Status line caption ink-faint: health dot + word · account identity · "synced {relative}"
  - ready/live → good "Connected"
  - syncing → watch "Syncing"
  - error → crit "Sync failing"
  - token_revoked → crit "Reconnect needed"
  - paused → ink-faint "Paused"
  - needs_setup → warn "Needs setup"
- Quick actions right-aligned: at most one primary + secondaries

7.3 The two-pane work surface

List pane — searchable, filterable, dense rows. Filters are ghost pills; search is a plain input, debounced 250ms.

Detail pane — title, metadata line, an action bar bounded by hairlines, then content. Empty: "Select a message to read it here."

7.4 Per-service mapping (all shells identical)

┌──────────────────┬─────────────────────────────────────┬──────────────────────────────────────────────┬────────────────────────────────────────────┐
│     Service      │                List                 │                    Detail                    │                   Writes                   │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ Gmail            │ messages                            │ subject, from, body (live)                   │ —                                          │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ Google Calendar  │ events                              │ title, time, attendees                       │ create event                               │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ Google Drive     │ files (live search)                 │ name, type, owner                            │ —                                          │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ GitHub           │ repositories                        │ PRs, commits, issues                         │ —                                          │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ Slack            │ channels                            │ recent activity                              │ —                                          │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ Outlook Mail     │ messages                            │ subject, from, body (live)                   │ mark read, flag, draft, reply, send        │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ Outlook Calendar │ events                              │ title, time, attendees                       │ create, update, cancel                     │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ Microsoft To Do  │ tasks                               │ title, due, importance, notes                │ create, update, complete, delete           │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ OneDrive         │ folders/files                       │ name, size, modified by                      │ create folder, upload text, rename, delete │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ OneNote          │ notebook › section › page           │ page text                                    │ create notebook/section/page, append       │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ Teams            │ channels                            │ messages (licence permitting)                │ —                                          │
├──────────────────┼─────────────────────────────────────┼──────────────────────────────────────────────┼────────────────────────────────────────────┤
│ Zoom             │ meetings (upcoming/past/recordings) │ topic, time, join link, agenda, participants │ schedule, edit, delete                     │
└──────────────────┴─────────────────────────────────────┴──────────────────────────────────────────────┴────────────────────────────────────────────┘

7.5 Capability states — teach, don't error

When a provider genuinely can't do something (free plan, missing scope, personal account), show a capability, not an error:

About this Zoom account
  Cloud recordings & transcripts — Cloud recording is part of Zoom's paid
  plans. This account records locally only, and local recordings never reach
  Zoom's API, so Sentinel cannot see them.

Four states: available · requires_plan · requires_scope · unknown. unknown must say "Sentinel could not check" — never guess.

Render as a dashed-border block at the bottom of the work surface, caption ink-faint. Never a red error. Never a modal.

7.6 Adding a future provider

A new provider requires: an icon, a name, a service key, a list renderer, a detail renderer, and its Action Registry actions. Nothing else. The header, rail, assistant, health, search, and action UX come free.

Data: GET /workspace/{service}/intelligence ✅ (provider-agnostic) + per-service read endpoints ✅.

---
8. INTELLIGENCE RAIL

One component, reused everywhere. It answers: "what does Sentinel know about what I'm looking at right now?"

8.1 Scoping rule

Show only what relates to the current provider/service/entity. On the Outlook Mail page, only Outlook findings and situations that include an Outlook finding. Never a global feed in a scoped context.

8.2 Sections, in order (each omitted entirely when empty)

┌────────────────────────────────┐
│ ◉ What Sentinel sees here      │
│                                │
│ SITUATIONS                     │
│ ┌────────────────────────────┐ │
│ │ heartbeat-harmony          │ │
│ │ Critical meetings and an   │ │
│ │ overdue task across three  │ │
│ │ services…                  │ │
│ │ → Prepare for the meeting  │ │
│ └────────────────────────────┘ │
│                                │
│ FINDINGS                       │
│ ● 3 important messages unread  │
│   Unread for over 14 days      │
│                                │
│ MEMORY                         │
│ 🧠 This has happened 2 times   │
└────────────────────────────────┘

Header: 13px ring glyph + "What Sentinel sees here" (small weight-600).

Section labels: micro uppercase ink-faint, +0.06em.

Findings: severity dot, title (truncate 1 line), why (truncate 1 line). Max 8.

Quiet state (connected, nothing to report):

▎ Nothing needs your attention in this service right now.

Not connected: rail is hidden entirely.

Loading: three skeleton rows.

Data: GET /workspace/{service}/intelligence ✅.

---
9. ASSISTANT

The assistant is a panel inside the shell, never a separate destination and never a floating bubble. It is the same intelligence, asked in words — not a second system.

9.1 Placement

Below the Intelligence Rail on Provider Workspace pages, 380px min-height. Also available at /assistant for open-ended questions in the current context.

9.2 Composition

- Small header: context label (e.g. "Microsoft 365") + context dot
- Message thread, small; user messages right-aligned in bg-surface-3, Sentinel's left-aligned plain on surface
- Input with placeholder tailored to the surface: "Ask about your mail…", "Ask about your meetings…"
- Suggested prompts as ghost pills only when the thread is empty — max 3, derived from what's actually on screen

9.3 Rules

- Never full-screen. Never auto-opens. Never interrupts.
- No typing indicators with animated dots — a single caption ink-faint "Thinking…" line.
- When the assistant proposes an action, it renders the same Action confirmation component as everywhere else (§10). It never executes anything directly.
- Answers cite what they're based on where possible, linking to the finding or item.

---
10. ACTION UX

Every write follows one path: Propose → Preview → Confirm → Execute → Verify → Audit → (Undo). One component (ActionButton) handles all of it, everywhere.

10.1 States

1 — Idle: the button. Label is a verb: "Schedule meeting", "Create task".

2 — Preview + confirm (everything external always confirms):
┌─────────────────────────────────────────────────┐
│ Schedule "Deploy review" on Fri 14 Aug at 15:00 │
│ Creates a real Zoom meeting and returns its join│
│ link. Nobody is invited or notified.            │
│                          [ Schedule ]  Cancel   │
└─────────────────────────────────────────────────┘
Inline, bg-surface/60, border, radius 4. The preview text comes from the server, never composed client-side.

3 — High-risk / irreversible — visually distinct and unmissable:
┌─────────────────────────────────────────────────┐
│ HIGH RISK · CANNOT BE UNDONE            (crit)  │
│ This sends a real email immediately. It cannot  │
│ be recalled or undone.                          │
│ ┌─────────────────────────────────────────────┐ │
│ │ To       jane@example.com                   │ │
│ │ Subject  Deployment postponed               │ │
│ │ Message  Hi Jane, …                         │ │
│ └─────────────────────────────────────────────┘ │
│              [ Send now ]   Cancel              │
└─────────────────────────────────────────────────┘
border-crit/50, bg-crit/5. Every recipient named individually — never "3 people". The confirm button is the only filled crit element permitted in the product.

4 — Executing: button shows "Working…", disabled.

5 — Result:
- succeeded → ✓ Done in good, with the server's verification line as caption ink-faint ("Zoom has 'Deploy review' at Fri 14 Aug 15:00")
- unknown → warn: "Applied, but Sentinel couldn't confirm it." — never shown as failure; the change may exist and reporting failure invites a duplicate
- failed → crit with the provider's own reason

6 — Undo: shown only when the action is genuinely compensatable.
- reversible / compensatable → Undo ghost link
- irreversible → no Undo button at all. Never a disabled one, never a tooltip promising otherwise.
- After undo, show the server's undo result: "The meeting was restored to its previous topic, time and agenda."

10.2 Honesty rules (non-negotiable)

- Never claim success without server verification.
- Never offer undo where none exists.
- Never hide that an action reaches other people.
- Compensation is described as compensation: "The event was deleted. Everyone invited has been notified of the cancellation — the invitation itself cannot be unsent."

10.3 Audit  /history

Table: time · action · target · risk · status · verification · who · undo state. Filter by provider, status, risk. This is a record, so a table is correct here.

Data: POST /actions, /actions/:id/approve|execute|undo, GET /workspaces/audit/actions ✅.

---
11. MEMORY UX

Memory is Sentinel's most distinctive moment. It must feel earned and quiet — never a gimmick.

11.1 The announcement toast

Appears once, when a memory is first formed:

┌────────────────────────────────────────────┐
│ 🧠  Sentinel will remember that            │
│                                            │
│ "heartbeat-harmony" keeps recurring —      │
│ seen 2 times.                              │
│                                            │
│ Why  This situation formed, resolved,      │
│      and formed again.                     │
│                                            │
│ [ View ]              [ Forget this ]      │
└────────────────────────────────────────────┘

- Bottom-right, 10s auto-dismiss, dismissible
- 🧠 is the only emoji in the product
- Announced once ever — never re-announced on later syncs

11.2 Memory page  /memory

Header h2 "What Sentinel remembers" + caption "Patterns Sentinel noticed by watching what keeps happening."

Each memory:
- Summary small ink
- Why Sentinel remembers this — the deterministic rule in plain words: "This situation has formed, resolved and formed again."
- Evidence — links to the situation occurrences
- Scope — context dot + "Personal" or workspace name
- First noticed / last seen timestamps
- Forget ghost button → confirmation → POST /memory/:id/forget

Forgotten memories are hidden by default behind a "Show forgotten" toggle, and render at 60% opacity with a "Forgotten" pill.

11.3 Where memory shows elsewhere

- Situation detail rail: "🧠 Seen 2 times"
- Decisions influenced by memory: 🧠 glyph + "Because this keeps recurring"
- Command Center rail: count + most recent

Data: GET /memory, GET /memory/announcements, POST /memory/:id/forget ✅.

---
12. SEARCH / GLOBAL COMMAND  ⌘K

Modal overlay, 640px, top-anchored at 15vh, overlay shadow.

┌──────────────────────────────────────────┐
│ 🔍 Search or type a command…             │
├──────────────────────────────────────────┤
│ SITUATIONS                               │
│  ● heartbeat-harmony      4 findings     │
│ FINDINGS                                 │
│  ● 3 important messages unread   Gmail   │
│ IN YOUR TOOLS                            │
│  ✉ Contract renewal — Jane      Gmail    │
│ GO TO                                    │
│  → Connections                           │
│ ACTIONS                                  │
│  + Schedule a meeting                    │
└──────────────────────────────────────────┘

- Opens on ⌘K / Ctrl+K; Esc closes; ↑↓ navigate; ↵ selects
- Results grouped and ranked in this order: Situations → Findings → Provider content → Navigation → Actions
- Debounce 200ms; skeleton rows while searching
- Empty query shows recent items + 5 common commands
- No results: "Nothing matched "xyz". Try a person, a repository, or a subject line."
- Scoped to the current context always; show the context dot in the header

Data: GET /search ✅ (currently narrower than this spec — build the UI to degrade gracefully to whatever it returns).

---
13. CONNECTIONS

Deliberately not the front door. Users come here to fix something or add something, then leave.

13.1 Overview  /connections

Header h2 "Connections" + caption "The tools Sentinel reads to understand your work."

Grouped by family, not flat. Each family is one card:

┌──────────────────────────────────────────────┐
│ [icon] Microsoft 365            ● Connected  │
│ you@example.com · 6 services                 │
│                                              │
│ ● Outlook Mail    ● Outlook Calendar         │
│ ● OneDrive        ● OneNote                  │
│ ● To Do           ○ Teams — needs a work acct│
│                                    [ Manage ]│
└──────────────────────────────────────────────┘

Not-connected families render at reduced emphasis with a Connect button and one line saying what connecting enables.

13.2 Provider detail  /connections/:provider

- Account identity + when connected
- Per-service rows: name, health, last sync, signal count, Pause / Resume / Disconnect
- Unavailable services listed explicitly with the honest reason:
▎ 🔒 Teams — Requires a Microsoft 365 Business or work/school aft account doesn't include it.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/c7e6e382-8191-487d-bd37-5cfa7557e754).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
