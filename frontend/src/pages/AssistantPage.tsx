import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  AttentionItem,
  DecisionRow,
  Goal,
  Investigation,
  MeetingBrief,
  MemoryRow,
  MyTeam,
  SentinelAction,
  SentinelStatus,
  SituationRow,
} from "../api/types";
import {
  classify,
  isDeterministic,
  LLM_BUDGET,
  QUICK_ASKS,
  resolveRequestOf,
  type Intent,
  type ResolveRequest,
} from "../components/assistant/intent";
import { AttentionRows, Chip, Composer, ContextRail } from "../components/assistant/CommandCenter";
import { InvestigationPanel } from "../components/InvestigationPanel";
import { MeetingBriefPanel } from "../components/MeetingBriefPanel";
import { PROVIDER_LABEL, relativeTime, severityOf } from "../components/situations";
import {
  openAttention,
  useIntelligence,
  type AssistantScope,
} from "../hooks/useIntelligence";
import {
  Action,
  ActionGroup,
  Badge,
  Icon,
  Overflow,
  OverflowItem,
  Spinner,
} from "../components/ui";
import type { Tone } from "../components/ui";

/**
 * The Sentinel Assistant - the primary interface.
 *
 * A conversation layer over the Intelligence Core, not a chatbot with database
 * access. Nothing in this file decides what matters: ranking is the attention
 * engine's `priority`, correlation is the situation engine's, recommendations
 * are the decision engine's, evidence is the investigation service's, and every
 * write leaves through the Action Registry's propose -> confirm -> execute ->
 * verify path. What lives here is routing - which existing capability answers
 * this question - and rendering.
 *
 * Three dimensions, all resolved before any data is read:
 *
 *   SCOPE     chosen explicitly in the header chip, never inferred from
 *             wording. Personal or one channel; the server re-checks
 *             membership on every channel endpoint regardless.
 *   PROVIDER  detected deterministically from the text and applied as a
 *             FILTER over Core data. The global Assistant never proxies a
 *             provider's live AI - that surface exists, keeps its own
 *             multi-step budget, and is linked to rather than wrapped.
 *   INTENT    deterministic regex (components/assistant/intent.ts).
 *
 * Answers are verdict-first: what it is, which providers it spans, what to do,
 * and only then - behind a disclosure - the reasoning. A paragraph is never
 * the first thing on screen.
 */
type Block =
  | { kind: "text"; text: string }
  | { kind: "catchup"; narrative: string | null; gapHours: number }
  | { kind: "attention"; items: AttentionItem[]; label?: string }
  | { kind: "situations"; rows: SituationRow[]; subject?: string }
  | { kind: "memory"; rows: MemoryRow[] }
  | { kind: "goals"; rows: Goal[] }
  | { kind: "decisions"; rows: DecisionRow[] }
  | { kind: "status"; status: SentinelStatus | null; connections: number; scope: AssistantScope; open: number }
  | { kind: "proposal"; action: SentinelAction; interpretation: string }
  | { kind: "prepare"; brief: MeetingBrief }
  | { kind: "investigation"; investigation: Investigation; path: string }
  | { kind: "choose"; items: AttentionItem[]; subject: string }
  | { kind: "provider"; provider: string; items: AttentionItem[]; rows: SituationRow[] }
  | { kind: "resolveChoose"; items: AttentionItem[]; request: ResolveRequest }
  | { kind: "resolved"; item: AttentionItem; request: ResolveRequest }
  | { kind: "notice"; title: string; body: string; to?: string; toLabel?: string }
  | { kind: "pending"; local: boolean };

interface Turn {
  id: string;
  role: "user" | "sentinel";
  text?: string;
  block?: Block;
}

let seq = 0;
const nextId = () => `t${++seq}`;

/** Provider AI panels that actually exist. A live provider question is handed
 *  to one of these by link; anything else is answered from Core data only. */
const PROVIDER_PANEL: Record<string, { to: string; label: string }> = {
  gmail: { to: "/connections/google", label: "Google" },
  google_calendar: { to: "/connections/google", label: "Google" },
  google_drive: { to: "/connections/google", label: "Google" },
  github: { to: "/connections/github", label: "GitHub" },
  microsoft_outlook_mail: { to: "/connections/microsoft", label: "Microsoft" },
  microsoft_outlook_calendar: { to: "/connections/microsoft", label: "Microsoft" },
  microsoft_todo: { to: "/connections/microsoft", label: "Microsoft" },
  microsoft_onedrive: { to: "/connections/microsoft", label: "Microsoft" },
  microsoft_onenote: { to: "/connections/microsoft", label: "Microsoft" },
};

/** Loose provider words -> the ids the Core actually stores, so "calendar"
 *  filters both Google and Outlook calendar items. */
const PROVIDER_GROUP: Record<string, string[]> = {
  calendar: ["google_calendar", "microsoft_outlook_calendar", "zoom"],
  mail: ["gmail", "microsoft_outlook_mail"],
  outlook: ["microsoft_outlook_mail", "microsoft_outlook_calendar"],
};

function providerIds(provider: string): string[] {
  return PROVIDER_GROUP[provider] ?? [provider];
}

function providerLabel(provider: string): string {
  return PROVIDER_LABEL[provider] ?? provider.replace(/_/g, " ");
}

export function AssistantPage() {
  const [scope, setScope] = useState<AssistantScope>({ kind: "personal" });
  const [teams, setTeams] = useState<MyTeam[]>([]);
  const intel = useIntelligence(scope);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLInputElement>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const handedOff = useRef<string | null>(null);

  const open = useMemo(() => openAttention(intel.attention), [intel.attention]);
  const nextMeeting = open.find((i) => i.type === "upcoming_meeting");
  const teamId = scope.kind === "channel" ? scope.teamId : null;

  useEffect(() => {
    api.get<MyTeam[]>("/teams/mine").then(setTeams).catch(() => setTeams([]));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  // The Dashboard hands questions over as ?q=… rather than answering them
  // itself, so every capability and every route to the Action Registry stays
  // in this one file.
  useEffect(() => {
    const q = searchParams.get("q");
    if (!q || handedOff.current === q) return;
    if (intel.loading) return;
    handedOff.current = q;
    setSearchParams({}, { replace: true });
    void submit(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, intel.loading]);

  function say(block: Block, replacePending = true) {
    setTurns((prev) => {
      const base =
        replacePending && prev[prev.length - 1]?.block?.kind === "pending" ? prev.slice(0, -1) : prev;
      return [...base, { id: nextId(), role: "sentinel", block }];
    });
  }

  /** Changing scope starts a new conversation: the answers above it were about
   *  a different Sentinel, and leaving them in place would invite reading a
   *  personal answer as a team one. */
  function changeScope(next: AssistantScope) {
    setScope(next);
    setTurns([]);
  }

  async function submit(raw: string) {
    const text = raw.trim();
    if (!text || busy) return;

    const { intent, subject, provider } = classify(text);

    setTurns((prev) => [
      ...prev,
      { id: nextId(), role: "user", text },
      { id: nextId(), role: "sentinel", block: { kind: "pending", local: isDeterministic(intent) } },
    ]);
    setInput("");
    setBusy(true);

    try {
      await route(intent, subject, provider, text);
    } catch (e) {
      say({
        kind: "notice",
        title: "That didn't go through",
        body: e instanceof Error ? e.message : "Something failed on the way to Sentinel.",
      });
    } finally {
      setBusy(false);
    }
  }

  /**
   * One question -> one existing capability.
   *
   * Every branch is either a read of `intel` (already in memory: zero network,
   * zero model) or exactly ONE server call. No branch calls the model, reads
   * the answer and calls again - the ceiling is declared per intent in
   * `LLM_BUDGET` and asserted here in development.
   */
  async function route(intent: Intent, subject: string | undefined, provider: string | undefined, text: string) {
    if (import.meta.env.DEV && !(LLM_BUDGET[intent] === 0 || LLM_BUDGET[intent] === 1)) {
      throw new Error(`Intent "${intent}" has no declared LLM budget`);
    }

    // A named provider narrows Core data rather than reaching the provider.
    const ids = provider ? providerIds(provider) : null;
    const byProvider = (items: AttentionItem[]) =>
      ids ? items.filter((i) => i.source_provider && ids.includes(i.source_provider)) : items;

    switch (intent) {
      case "catchup": {
        // Requested here rather than on mount: the endpoint advances the
        // last-seen marker as a side effect, so fetching it speculatively
        // consumed the very window it was meant to report on.
        const recap = intel.catchup ?? (await intel.loadCatchup());
        say({ kind: "catchup", narrative: recap?.narrative ?? null, gapHours: recap?.gap_hours ?? 0 });
        return;
      }

      case "attention":
        say({ kind: "attention", items: byProvider(open).slice(0, 6) });
        return;

      case "findings":
        // What Sentinel detected, as opposed to what you wrote down - the same
        // `origin` split the Findings page is built on.
        say({
          kind: "attention",
          items: byProvider(open.filter((i) => i.origin === "detected")).slice(0, 6),
          label: "detected",
        });
        return;

      case "situations": {
        const rows = ids
          ? intel.situations.filter((s) => s.providers.some((p) => ids.includes(p)))
          : intel.situations;
        say({ kind: "situations", rows });
        return;
      }

      case "memory":
        say({ kind: "memory", rows: intel.memories });
        return;

      case "goals":
        say({ kind: "goals", rows: intel.goals });
        return;

      case "decisions":
        say({ kind: "decisions", rows: intel.decisions });
        return;

      case "status":
        say({
          kind: "status",
          status: intel.status,
          connections: intel.connections.length,
          scope,
          open: open.length,
        });
        return;

      case "investigate":
      case "search": {
        const q = (subject ?? text).toLowerCase();
        const matches = open.filter((i) => `${i.title} ${i.why}`.toLowerCase().includes(q));
        const rows = intel.situations.filter((s) =>
          `${s.entity ?? ""} ${s.title}`.toLowerCase().includes(q),
        );

        // "Why?" is answered by the Investigation service, which retrieves
        // real evidence and is cached per item+scope - one call the first
        // time, none after. Only an unambiguous match is investigated; two
        // candidates get a list to pick from rather than a guess.
        if (intent === "investigate" && matches.length === 1) {
          await runInvestigation(matches[0]!);
          return;
        }
        if (intent === "investigate" && matches.length > 1) {
          say({ kind: "choose", items: matches.slice(0, 6), subject: subject ?? text });
          return;
        }

        if (rows.length === 0 && matches.length === 0) {
          say({
            kind: "notice",
            title: `Nothing about "${subject ?? text}" yet`,
            body: ids
              ? `Sentinel searches what it has already analysed from ${providerLabel(provider!)}, not that service live. Something recent may not have synced yet.`
              : "Sentinel searches what it has already analysed — findings and situations — rather than querying your providers live. Something recent may not have synced yet.",
            ...(ids && PROVIDER_PANEL[ids[0]!]
              ? { to: PROVIDER_PANEL[ids[0]!]!.to, toLabel: `Search ${PROVIDER_PANEL[ids[0]!]!.label} live` }
              : {}),
          });
          return;
        }
        if (rows.length > 0) say({ kind: "situations", rows, subject });
        if (matches.length > 0) say({ kind: "attention", items: matches.slice(0, 6) }, rows.length === 0);
        return;
      }

      case "prepare": {
        if (!nextMeeting) {
          say({
            kind: "notice",
            title: "No meeting to prepare for",
            body: "Nothing upcoming is on the calendar in the window Sentinel watches.",
          });
          return;
        }
        const brief = await api.post<MeetingBrief>(`/attention/${nextMeeting.id}/prepare`);
        say({ kind: "prepare", brief });
        return;
      }

      case "action": {
        // Straight into the Action Registry. The model may only fill in a key
        // that already exists there, and this path has no route to execution -
        // the card below is a proposal a person still has to confirm.
        const path = teamId ? `/teams/${teamId}/actions/from-text` : "/actions/from-text";
        const res = await api.post<{ action: SentinelAction; interpretation: string }>(path, { text });
        say({ kind: "proposal", action: res.action, interpretation: res.interpretation });
        return;
      }

      case "provider": {
        // A provider was named but no other intent matched. Answer from what
        // the Core has already analysed for that provider - never by querying
        // the provider live, which is what its own AI panel is for.
        const items = byProvider(open).slice(0, 6);
        const rows = intel.situations.filter((s) => s.providers.some((p) => ids!.includes(p)));
        say({ kind: "provider", provider: provider!, items, rows });
        return;
      }

      case "resolve": {
        // "this" is whatever the conversation is currently about. Resolved
        // deterministically from the last block that carried items - never
        // from the model, and never from a guess when there is more than one
        // candidate.
        const targets = lastShownItems();
        if (targets.length === 0) {
          say({
            kind: "notice",
            title: "Nothing to act on yet",
            body: "Ask what's urgent or what Sentinel detected first, then say “mark this done”.",
          });
          return;
        }
        const request = resolveRequestOf(text);
        if (targets.length > 1) {
          say({ kind: "resolveChoose", items: targets.slice(0, 6), request });
          return;
        }
        await applyResolve(targets[0]!, request);
        return;
      }

      case "remember":
        say({
          kind: "notice",
          title: "I can't store that yet",
          body: "Sentinel's memory forms on its own, when the same situation happens more than once — it can't yet take an instruction to remember something.",
          to: "/memory",
          toLabel: "See what Sentinel remembers",
        });
        return;

      default: {
        // The one open-ended path, and the only one that reaches the model
        // from here. Its context is built server-side from the Core.
        const { reply } = await api.post<{ reply: string }>("/assistant/chat", {
          message: text,
          history: turns
            .filter((t) => t.text || t.block?.kind === "text")
            .slice(-10)
            .map((t) => ({
              role: t.role === "user" ? "user" : "assistant",
              content: t.text ?? (t.block?.kind === "text" ? t.block.text : ""),
            })),
        });
        say({ kind: "text", text: reply });
      }
    }
  }

  /** What "this" refers to: the items from the most recent block that showed
   *  any. Reading backwards means "mark this done" after a list acts on that
   *  list, not on something five turns ago. */
  function lastShownItems(): AttentionItem[] {
    for (let i = turns.length - 1; i >= 0; i--) {
      const b = turns[i]?.block;
      if (b?.kind === "attention" && b.items.length > 0) return b.items;
      if (b?.kind === "provider" && b.items.length > 0) return b.items;
      if (b?.kind === "choose" && b.items.length > 0) return b.items;
    }
    return [];
  }

  /**
   * Straight to the Action Registry - no model, no second execution path.
   *
   * PATCH /attention/{id} is now a thin adapter over propose -> execute, so
   * this is the same audited, verified, undoable action the attention list
   * itself performs. The optimistic drop matches every other surface.
   */
  async function applyResolve(item: AttentionItem, request: ResolveRequest) {
    intel.dropAttention(item.id);
    const body =
      request.state === "snoozed"
        ? {
            state: "snoozed",
            snoozed_until: new Date(Date.now() + (request.hours ?? 24) * 3600 * 1000).toISOString(),
          }
        : { state: request.state };
    try {
      await api.patch(`/attention/${item.id}`, body);
      say({ kind: "resolved", item, request });
    } catch (e) {
      intel.restoreAttention(item);
      say({
        kind: "notice",
        title: "That didn't go through",
        body: e instanceof Error ? e.message : "Sentinel couldn't apply that change.",
      });
    }
  }

  /** The existing investigation endpoints, scoped. Cached server-side per
   *  item+scope, so re-asking the same "why" costs nothing. */
  async function runInvestigation(item: AttentionItem) {
    const path = teamId
      ? `/teams/${teamId}/attention/${item.id}/investigate`
      : `/attention/${item.id}/investigate`;
    const investigation = await api.post<Investigation>(path);
    say({ kind: "investigation", investigation, path });
  }

  async function resolve(item: AttentionItem, state: "done" | "snoozed") {
    intel.dropAttention(item.id);
    const body =
      state === "snoozed"
        ? { state, snoozed_until: new Date(Date.now() + 24 * 3600 * 1000).toISOString() }
        : { state };
    try {
      await api.patch(`/attention/${item.id}`, body);
    } catch {
      intel.restoreAttention(item);
    }
  }

  const started = turns.length > 0;

  return (
    <div className="flex gap-6">
      <div className="flex min-h-[calc(100vh-9rem)] min-w-0 flex-1 flex-col">
        <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-h2 font-semibold tracking-tight text-ink">Assistant</h1>
            <p className="mt-1 text-small text-ink-dim">
              Everything Sentinel watches, in one place.
            </p>
          </div>
          <ScopeChip scope={scope} teams={teams} onChange={changeScope} />
        </header>

        <div className="flex-1 pb-4">
          {started ? (
            <div className="flex flex-col gap-5">
              {turns.map((t) => (
                <TurnView
                  key={t.id}
                  turn={t}
                  onResolve={resolve}
                  onAsk={(q) => void submit(q)}
                  onInvestigate={(item) => void runInvestigation(item)}
                  onApplyResolve={(item, request) => void applyResolve(item, request)}
                />
              ))}
            </div>
          ) : (
            <OpeningState loading={intel.loading} onAsk={(q) => void submit(q)} />
          )}
          <div ref={endRef} />
        </div>

        <Composer
          value={input}
          onChange={setInput}
          onSubmit={() => void submit(input)}
          busy={busy}
          showSuggestions={!started}
          onSuggest={(s) => void submit(s)}
          inputRef={composerRef}
        />
      </div>

      <ContextRail intel={intel} onAsk={(q) => void submit(q)} />
    </div>
  );
}

/* ------------------------------------------------------------- header -- */

/**
 * Which Sentinel is being asked, always visible and never inferred.
 *
 * Scope changes what data is read and what a member is authorized to see, so
 * it is a deliberate choice rather than something parsed out of a sentence -
 * a mis-read "for the team" that silently answered about the wrong scope is
 * the one kind of wrongness this product cannot afford.
 */
function ScopeChip({
  scope,
  teams,
  onChange,
}: {
  scope: AssistantScope;
  teams: MyTeam[];
  onChange: (s: AssistantScope) => void;
}) {
  const label = scope.kind === "personal" ? "Personal" : scope.name;
  return (
    <Overflow
      label="Assistant scope"
      align="right"
      trigger={
        <>
          <Icon name={scope.kind === "personal" ? "user" : "hash"} size={13} />
          {label}
          <Icon name="more" size={12} className="rotate-90" />
        </>
      }
      triggerClassName="inline-flex h-[34px] items-center gap-1.5 rounded-md border border-border px-3 text-caption font-medium text-ink-dim transition-colors hover:border-border-strong hover:text-ink"
    >
      {(close) => (
        <>
          <OverflowItem
            onClick={() => {
              onChange({ kind: "personal" });
              close();
            }}
          >
            {scope.kind === "personal" ? "✓ " : ""}Personal
          </OverflowItem>
          {teams.map((t) => (
            <OverflowItem
              key={t.id}
              onClick={() => {
                onChange({ kind: "channel", teamId: t.id, name: t.name });
                close();
              }}
            >
              {scope.kind === "channel" && scope.teamId === t.id ? "✓ " : ""}
              {t.name}
            </OverflowItem>
          ))}
        </>
      )}
    </Overflow>
  );
}

/** Not "how can I help?" - the questions Sentinel can actually answer, each
 *  phrased the way the router recognises it, so the opening screen teaches the
 *  vocabulary and every one of them costs zero LLM calls. */
function OpeningState({ loading, onAsk }: { loading: boolean; onAsk: (q: string) => void }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-5">
      <div className="mb-3 flex items-center gap-2">
        <p className="text-small font-medium text-ink">Start here</p>
        {loading && <Spinner size="sm" />}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {QUICK_ASKS.map((q) => (
          <Chip key={q} onClick={() => onAsk(q)}>
            {q}
          </Chip>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ one turn -- */

function TurnView({
  turn,
  onResolve,
  onAsk,
  onInvestigate,
  onApplyResolve,
}: {
  turn: Turn;
  onResolve: (i: AttentionItem, s: "done" | "snoozed") => void;
  onAsk: (q: string) => void;
  onInvestigate: (item: AttentionItem) => void;
  onApplyResolve: (item: AttentionItem, request: ResolveRequest) => void;
}) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-lg rounded-br-sm bg-surface-2 px-3.5 py-2 text-small text-ink">
          {turn.text}
        </p>
      </div>
    );
  }

  const b = turn.block;
  if (!b) return null;

  return (
    <div className="flex gap-2.5">
      <span
        className="mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-full border border-accent/40 bg-accent/10"
        aria-hidden="true"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-accent" />
      </span>

      <div className="min-w-0 flex-1">
        {b.kind === "pending" && (
          <span className="inline-flex items-center gap-2 text-caption text-ink-faint">
            <Spinner size="sm" /> {b.local ? "Reading the Core…" : "Thinking…"}
          </span>
        )}

        {b.kind === "text" && (
          <p className="whitespace-pre-wrap text-small leading-relaxed text-ink-dim">{b.text}</p>
        )}

        {b.kind === "catchup" && (
          <>
            <p className="whitespace-pre-wrap text-small leading-relaxed text-ink-dim">
              {b.narrative ?? "Nothing has changed since you were last here."}
            </p>
            {b.gapHours >= 1 && (
              <p className="mt-1.5 text-micro text-ink-faint">
                Covering the last{" "}
                {b.gapHours < 48 ? `${Math.round(b.gapHours)} hours` : `${Math.round(b.gapHours / 24)} days`}.
              </p>
            )}
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              <Chip onClick={() => onAsk("What's urgent?")}>What's urgent?</Chip>
              <Chip onClick={() => onAsk("What's happening?")}>What's happening?</Chip>
            </div>
          </>
        )}

        {b.kind === "attention" &&
          (b.items.length === 0 ? (
            <p className="text-small text-ink-dim">
              {b.label === "detected"
                ? "Sentinel hasn't detected anything open right now."
                : "Nothing is open right now."}
            </p>
          ) : (
            <>
              <p className="mb-2 text-small text-ink-dim">
                {b.items.length} {b.label === "detected" ? "finding" : "thing"}
                {b.items.length === 1 ? "" : "s"}, most pressing first.
              </p>
              <AttentionRows items={b.items} onResolve={onResolve} />
            </>
          ))}

        {b.kind === "situations" &&
          (b.rows.length === 0 ? (
            <p className="text-small text-ink-dim">
              {b.subject
                ? `Nothing correlated about “${b.subject}”.`
                : "No situations right now. They form when two or more findings point at the same thing."}
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {b.rows.slice(0, 5).map((s) => (
                <li key={s.id}>
                  <SituationVerdict situation={s} />
                </li>
              ))}
            </ul>
          ))}

        {b.kind === "choose" && (
          <>
            <p className="mb-2 text-small text-ink-dim">
              {b.items.length} things match “{b.subject}”. Which one?
            </p>
            <ul className="flex flex-col gap-1.5">
              {b.items.map((i) => (
                <li key={i.id}>
                  <button
                    type="button"
                    onClick={() => onInvestigate(i)}
                    className="flex w-full items-center justify-between gap-3 rounded-md border border-border bg-surface px-3.5 py-2.5 text-left transition-colors hover:border-border-strong"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-small text-ink">{i.title}</span>
                      <span className="block truncate text-micro text-ink-faint">{i.why}</span>
                    </span>
                    <Icon name="sparkle" size={13} className="flex-none text-ink-faint" />
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        {b.kind === "investigation" && <InvestigationBlock initial={b.investigation} path={b.path} />}

        {b.kind === "resolveChoose" && (
          <>
            <p className="mb-2 text-small text-ink-dim">
              {b.items.length} things are open. Which one should I {RESOLVE_VERB[b.request.state]}?
            </p>
            <ul className="flex flex-col gap-1.5">
              {b.items.map((i) => (
                <li key={i.id}>
                  <button
                    type="button"
                    onClick={() => onApplyResolve(i, b.request)}
                    className="flex w-full items-center justify-between gap-3 rounded-md border border-border bg-surface px-3.5 py-2.5 text-left transition-colors hover:border-border-strong"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-small text-ink">{i.title}</span>
                      <span className="block truncate text-micro text-ink-faint">{i.why}</span>
                    </span>
                    <Icon name="check" size={13} className="flex-none text-ink-faint" />
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        {/* Report: what was done, to what, and where the record is. */}
        {b.kind === "resolved" && (
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="good">
              {b.request.state === "snoozed"
                ? `Snoozed ${SNOOZE_LABEL[b.request.hours ?? 24] ?? "for a while"}`
                : b.request.state === "dismissed"
                  ? "Dismissed"
                  : "Marked done"}
            </Badge>
            <span className="min-w-0 truncate text-small text-ink-dim">{b.item.title}</span>
            <Link to="/history" className="text-caption text-accent-text hover:underline">
              View activity →
            </Link>
          </div>
        )}

        {b.kind === "provider" && (
          <ProviderBlock
            provider={b.provider}
            items={b.items}
            rows={b.rows}
            onResolve={onResolve}
          />
        )}

        {b.kind === "memory" &&
          (b.rows.length === 0 ? (
            <p className="text-small text-ink-dim">
              Nothing yet. Memory forms when the same situation happens more than once.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {b.rows.slice(0, 5).map((m) => (
                <li key={m.id} className="rounded-md border border-good/25 bg-good/[0.05] px-3.5 py-2.5">
                  <p className="text-small text-ink">{m.summary}</p>
                  <p className="mt-0.5 text-micro text-ink-faint">
                    Seen {m.observation_count} time{m.observation_count === 1 ? "" : "s"} · last{" "}
                    {relativeTime(m.last_observed_at)}
                  </p>
                </li>
              ))}
            </ul>
          ))}

        {b.kind === "goals" &&
          (b.rows.length === 0 ? (
            <p className="text-small text-ink-dim">
              No goals set yet. Goals give Sentinel something to measure activity against.
            </p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {b.rows.slice(0, 5).map((g) => (
                <li
                  key={g.id}
                  className="flex items-start justify-between gap-3 rounded-md border border-border bg-surface px-3.5 py-2.5"
                >
                  <div className="min-w-0">
                    <p className="text-small text-ink">{g.title}</p>
                    <p className="mt-0.5 text-micro text-ink-faint">
                      {/* The engine's own numbers. `progress === null` is a real
                          answer - never rendered as a confident 0%. */}
                      {g.progress !== null
                        ? `${Math.round(g.progress * 100)}% complete`
                        : "Progress not yet measurable"}
                    </p>
                  </div>
                  <Badge tone={GOAL_TONE[g.health] ?? "neutral"}>{GOAL_LABEL[g.health] ?? "Not assessed"}</Badge>
                </li>
              ))}
            </ul>
          ))}

        {b.kind === "decisions" &&
          (b.rows.length === 0 ? (
            <p className="text-small text-ink-dim">
              Nothing to recommend right now. Proposals form when a situation is grounded enough to act on.
            </p>
          ) : (
            <>
              <p className="mb-2 text-small text-ink-dim">
                {b.rows.length} proposal{b.rows.length === 1 ? "" : "s"} — each still needs your confirmation.
              </p>
              <ul className="flex flex-col gap-1.5">
                {b.rows.slice(0, 5).map((d) => (
                  <li key={d.id} className="rounded-md border border-border bg-surface px-3.5 py-2.5">
                    <p className="text-small text-ink">{d.action}</p>
                    <p className="mt-0.5 text-micro text-ink-faint">{d.rationale}</p>
                  </li>
                ))}
              </ul>
            </>
          ))}

        {b.kind === "status" && <StatusBlock block={b} />}

        {b.kind === "prepare" && (
          <MeetingBriefPanel brief={b.brief} refreshing={false} onRefresh={() => {}} onClose={() => {}} />
        )}

        {b.kind === "proposal" && <ProposalCard action={b.action} interpretation={b.interpretation} />}

        {b.kind === "notice" && (
          <div className="rounded-md border border-border bg-surface px-3.5 py-3">
            <p className="text-small font-medium text-ink">{b.title}</p>
            <p className="mt-1 text-caption leading-relaxed text-ink-dim">{b.body}</p>
            {b.to && (
              <Link to={b.to} className="mt-2 inline-block text-caption text-accent-text hover:underline">
                {b.toLabel ?? "Open"} →
              </Link>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- blocks -- */

const RESOLVE_VERB: Record<ResolveRequest["state"], string> = {
  done: "mark done",
  dismissed: "dismiss",
  snoozed: "snooze",
};

const SNOOZE_LABEL: Record<number, string> = {
  3: "for a few hours",
  24: "until tomorrow",
  [24 * 7]: "until next week",
};

const GOAL_LABEL: Record<Goal["health"], string> = {
  on_track: "On track",
  at_risk: "At risk",
  blocked: "Blocked",
  achieved: "Achieved",
  abandoned: "Abandoned",
  unknown: "Cannot yet be determined",
};

const GOAL_TONE: Record<Goal["health"], Tone> = {
  on_track: "good",
  at_risk: "warn",
  blocked: "crit",
  achieved: "good",
  abandoned: "neutral",
  unknown: "neutral",
};

/**
 * A provider question, answered from the Core.
 *
 * Everything here is already-analysed data filtered to one provider - zero
 * model calls. What it deliberately does NOT do is query the provider: the
 * per-provider AI panels own live access and their own multi-step budget, so
 * a genuinely live question gets a link there rather than a proxy through
 * here that would break the one-call rule invisibly.
 */
function ProviderBlock({
  provider,
  items,
  rows,
  onResolve,
}: {
  provider: string;
  items: AttentionItem[];
  rows: SituationRow[];
  onResolve: (i: AttentionItem, s: "done" | "snoozed") => void;
}) {
  const panel = providerIds(provider)
    .map((id) => PROVIDER_PANEL[id])
    .find(Boolean);
  const empty = items.length === 0 && rows.length === 0;

  return (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge tone="outline">{providerLabel(provider)}</Badge>
        <span className="text-small text-ink-dim">
          {empty
            ? "Nothing open from here right now."
            : `${items.length + rows.length} thing${items.length + rows.length === 1 ? "" : "s"} Sentinel has analysed.`}
        </span>
      </div>

      {rows.length > 0 && (
        <ul className="mb-2 flex flex-col gap-2">
          {rows.slice(0, 3).map((s) => (
            <li key={s.id}>
              <SituationVerdict situation={s} />
            </li>
          ))}
        </ul>
      )}

      {items.length > 0 && <AttentionRows items={items} onResolve={onResolve} />}

      {panel && (
        <p className="mt-2 text-micro text-ink-faint">
          Sentinel answers from what it has already analysed.{" "}
          <Link to={panel.to} className="text-accent-text hover:underline">
            Search {panel.label} live →
          </Link>
        </p>
      )}
    </>
  );
}

/**
 * The existing InvestigationPanel, with the one thing a conversation needs
 * that a page did not: its own copy of the result, so "re-investigate" shows
 * the new answer instead of silently refetching behind an unchanged card.
 *
 * `?refresh=true` is the only way past the server-side cache, so the plain
 * mount stays free after the first ask.
 */
function InvestigationBlock({ initial, path }: { initial: Investigation; path: string }) {
  const [investigation, setInvestigation] = useState(initial);
  const [refreshing, setRefreshing] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  async function refresh() {
    setRefreshing(true);
    try {
      setInvestigation(await api.post<Investigation>(`${path}?refresh=true`));
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <InvestigationPanel
      investigation={investigation}
      refreshing={refreshing}
      onRefresh={() => void refresh()}
      onClose={() => setDismissed(true)}
    />
  );
}

/**
 * Verdict -> context -> what to do.
 *
 * The heading is the engine's own entity/title, the chips are the providers it
 * actually spans, and the actions are the two real destinations. There is no
 * prose here by design: a correlated situation is a deterministic count of
 * findings against a shared entity, and the reasoning lives one click away in
 * the situation page or the investigation - not dumped as a paragraph.
 */
function SituationVerdict({ situation }: { situation: SituationRow }) {
  const sev = severityOf(situation.severity);
  return (
    <div className="rounded-lg border border-border bg-surface p-3.5">
      <div className="flex items-start gap-2.5">
        <span className={`mt-1.5 h-1.5 w-1.5 flex-none rounded-full ${sev.dot}`} aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="text-small font-medium leading-snug text-ink">
            {situation.entity ?? situation.title}
          </p>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-micro text-ink-faint">
            <Badge tone={sev.tone}>{sev.label}</Badge>
            {/* Only providers actually involved in this answer. */}
            {situation.providers.map((p) => (
              <Badge key={p} tone="outline">
                {providerLabel(p)}
              </Badge>
            ))}
            <span>
              {situation.member_count} related finding{situation.member_count === 1 ? "" : "s"}
            </span>
            {situation.occurrence_count > 1 && <span>· seen {situation.occurrence_count}×</span>}
          </div>

          <div className="mt-2.5">
            <Link
              to={`/situations/${situation.id}`}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-caption font-medium text-ink-dim transition-colors hover:border-border-strong hover:text-ink"
            >
              <Icon name="layers" size={13} /> View situation
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusBlock({
  block,
}: {
  block: Extract<Block, { kind: "status" }>;
}) {
  // A channel has no /attention/status of its own, so its answer is built from
  // what was genuinely loaded for it rather than a personal number relabelled.
  if (block.scope.kind === "channel") {
    return (
      <p className="text-small leading-relaxed text-ink-dim">
        Watching {block.scope.name} — {block.open} open item{block.open === 1 ? "" : "s"} from the
        connections this channel is authorized for.
      </p>
    );
  }

  if (block.status === null) {
    return <p className="text-small text-ink-dim">Sentinel couldn't read its own status just now.</p>;
  }

  return (
    <>
      <p className="text-small leading-relaxed text-ink-dim">
        Watching {block.connections} connected service{block.connections === 1 ? "" : "s"} across{" "}
        {block.status.provider_count} provider{block.status.provider_count === 1 ? "" : "s"} —{" "}
        {block.status.signals_analysed.toLocaleString()} signals analysed.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Badge tone={block.status.critical_count > 0 ? "crit" : "good"}>
          {block.status.critical_count} critical
        </Badge>
        <Badge tone="neutral">{block.status.review_count} to review</Badge>
        {block.status.last_synced_at && (
          <span className="text-micro text-ink-faint">
            Last synced {relativeTime(block.status.last_synced_at)}
          </span>
        )}
      </div>
      {block.status.errors.length > 0 && (
        <p className="mt-2 text-caption text-crit">{block.status.errors[0]}</p>
      )}
    </>
  );
}

/**
 * propose -> confirm -> execute -> verify, in a card.
 *
 * Nothing here talks to a provider. Every step is an Action Registry call, and
 * the card cannot skip the confirmation: the server decides whether approval is
 * required and this only ever renders what it sent back.
 */
function ProposalCard({ action, interpretation }: { action: SentinelAction; interpretation: string }) {
  const [current, setCurrent] = useState(action);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fields = (current.preview?.fields ?? {}) as Record<string, unknown>;
  const done = current.status === "succeeded" || current.status === "unknown";

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      if (current.status === "awaiting_approval" || current.status === "proposed") {
        await api.post(`/actions/${current.id}/approve`);
      }
      const res = await api.post<SentinelAction>(`/actions/${current.id}/execute`);
      setCurrent(res);
      if (res.status === "failed") setError(res.error ?? "The provider refused that.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't go through.");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    try {
      await api.post(`/actions/${current.id}/reject`);
      setCurrent({ ...current, status: "rejected" });
    } catch {
      setError("Couldn't cancel that.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-accent/30 bg-accent/[0.05] p-4">
      <p className="text-small text-ink-dim">{interpretation}</p>

      <div className="my-3 rounded-md border border-border bg-surface p-3">
        <p className="mb-2 text-micro font-semibold uppercase tracking-wide text-ink-faint">
          Proposed action
        </p>
        <p className="mb-2 text-small font-semibold capitalize text-ink">
          {(current.preview?.title as string) ?? current.action_type.replace(/_/g, " ")}
        </p>
        <dl className="flex flex-col gap-1.5">
          {Object.entries(fields).map(([k, v]) => (
            <div key={k} className="flex gap-3">
              <dt className="w-24 flex-none text-micro capitalize text-ink-faint">{k.replace(/_/g, " ")}</dt>
              <dd className="min-w-0 flex-1 break-words text-caption text-ink">{String(v)}</dd>
            </div>
          ))}
        </dl>
        {current.preview?.effect && (
          <p className="mt-2 text-micro text-ink-faint">{current.preview.effect}</p>
        )}
      </div>

      {current.status === "rejected" ? (
        <p className="text-caption text-ink-faint">Cancelled — nothing was sent.</p>
      ) : done ? (
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="good">Completed</Badge>
          {current.verification && (
            <span className="text-micro text-ink-faint">Verified: {current.verification}</span>
          )}
          {current.status === "unknown" && (
            <span className="text-micro text-warn">Applied, but Sentinel couldn't confirm it.</span>
          )}
          <Link to="/history" className="text-caption text-accent-text hover:underline">
            View activity →
          </Link>
        </div>
      ) : (
        <ActionGroup>
          <Action kind="confirm" loading={busy} onClick={() => void confirm()} />
          <Action kind="cancel" onClick={() => void cancel()} disabled={busy} />
        </ActionGroup>
      )}
      {error && <p className="mt-2 text-caption text-crit">{error}</p>}
    </div>
  );
}
