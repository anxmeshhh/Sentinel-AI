import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  AttentionItem,
  CatchUp,
  MeetingBrief,
  MemoryRow,
  SentinelAction,
  SituationRow,
} from "../api/types";
import { classify, type Intent } from "../components/assistant/intent";
import { AttentionRows, Chip, Composer, ContextRail } from "../components/assistant/CommandCenter";
import { MeetingBriefPanel } from "../components/MeetingBriefPanel";
import { SituationCard } from "../components/SituationCard";
import { relativeTime } from "../components/situations";
import { openAttention, useIntelligence } from "../hooks/useIntelligence";
import {
  Action,
  ActionGroup,
  Badge,
  Icon,
  Spinner,
} from "../components/ui";
import type { IconName } from "../components/ui";

/**
 * The Sentinel Assistant - the primary interface.
 *
 * This is a conversation layer over the Intelligence Core, not a chatbot with
 * database access. The distinction shows up in one place: nothing in this file
 * decides what matters. Ranking is the attention engine's `priority`,
 * correlation is the situation engine's, recommendations are the decision
 * engine's, and every write leaves through the Action Registry's
 * propose -> confirm -> execute -> verify path. What lives here is routing -
 * which existing capability answers this question - and rendering.
 *
 * It opens proactively rather than with a prompt. "How can I help?" puts the
 * work of knowing what to ask onto the person who came here precisely because
 * they don't know what happened; the cards and the attention list answer that
 * before they type anything.
 *
 * Two capabilities are deliberately absent and say so when asked: user-authored
 * memory ("remember that…") and live cross-provider search. Neither has a
 * backend endpoint, and a client-side imitation would put a fabricated memory
 * or a fabricated search result in front of someone with every reason to trust
 * it. Saying "I can't yet" costs one interaction; the alternative costs the
 * product's only real claim.
 */
type Block =
  | { kind: "text"; text: string }
  | { kind: "catchup"; narrative: string | null; gapHours: number }
  | { kind: "attention"; items: AttentionItem[] }
  | { kind: "situations"; rows: SituationRow[]; subject?: string }
  | { kind: "memory" }
  | { kind: "proposal"; action: SentinelAction; interpretation: string }
  | { kind: "prepare"; brief: MeetingBrief }
  | { kind: "notice"; title: string; body: string; to?: string; toLabel?: string }
  | { kind: "pending" };

interface Turn {
  id: string;
  role: "user" | "sentinel";
  text?: string;
  block?: Block;
}

let seq = 0;
const nextId = () => `t${++seq}`;

export function AssistantPage() {
  const intel = useIntelligence();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLInputElement>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  // StrictMode double-invokes effects in development, and clearing the param
  // re-runs this one - both of which submitted the handed-off question twice.
  // The ref makes the handover idempotent regardless of how often it fires.
  const handedOff = useRef<string | null>(null);

  const open = useMemo(() => openAttention(intel.attention), [intel.attention]);
  const nextMeeting = open.find((i) => i.type === "upcoming_meeting");

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  // The Dashboard hands questions over as ?q=… rather than answering them
  // itself, so every capability and every route to the Action Registry stays
  // in this one file. The param is cleared immediately so a refresh does not
  // silently re-run the question.
  useEffect(() => {
    const q = searchParams.get("q");
    if (!q || handedOff.current === q) return;
    // Wait for the Core to load first. Several intents answer straight from
    // `intel` - "what's urgent" reads the attention list - so running on mount
    // answered "nothing is open" while the fetch was still in flight.
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

  async function submit(raw: string) {
    const text = raw.trim();
    if (!text || busy) return;

    setTurns((prev) => [
      ...prev,
      { id: nextId(), role: "user", text },
      { id: nextId(), role: "sentinel", block: { kind: "pending" } },
    ]);
    setInput("");
    setBusy(true);

    const { intent, subject } = classify(text);
    try {
      await route(intent, subject, text);
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

  async function route(intent: Intent, subject: string | undefined, text: string) {
    switch (intent) {
      case "catchup": {
        const recap =
          intel.catchup ?? (await api.get<CatchUp>("/attention/catchup").catch(() => null));
        say({ kind: "catchup", narrative: recap?.narrative ?? null, gapHours: recap?.gap_hours ?? 0 });
        return;
      }

      case "attention":
        say({ kind: "attention", items: open.slice(0, 6) });
        return;

      case "situations":
        say({ kind: "situations", rows: intel.situations });
        return;

      case "memory":
        say({ kind: "memory" });
        return;

      case "investigate":
      case "search": {
        // Matches against what the Core has already concluded - Situations and
        // open findings. This is not a live provider search, and the empty
        // result below says so rather than implying Sentinel looked everywhere.
        const q = (subject ?? text).toLowerCase();
        const rows = intel.situations.filter((s) =>
          `${s.entity ?? ""} ${s.title}`.toLowerCase().includes(q),
        );
        const items = open.filter((i) => `${i.title} ${i.why}`.toLowerCase().includes(q));

        if (rows.length === 0 && items.length === 0) {
          say({
            kind: "notice",
            title: `Nothing about "${subject ?? text}" yet`,
            body: "Sentinel searches what it has already analysed — findings and situations — rather than querying your providers live. Something recent may not have synced yet.",
          });
          return;
        }
        if (rows.length > 0) say({ kind: "situations", rows, subject });
        if (items.length > 0) say({ kind: "attention", items: items.slice(0, 6) }, rows.length === 0);
        return;
      }

      case "prepare": {
        if (!nextMeeting) {
          say({
            kind: "notice",
            title: "No meeting to prepare for",
            body: "Nothing upcoming is on your calendar in the window Sentinel watches.",
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
        const res = await api.post<{ action: SentinelAction; interpretation: string }>(
          "/actions/from-text",
          { text },
        );
        say({ kind: "proposal", action: res.action, interpretation: res.interpretation });
        return;
      }

      case "remember":
        say({
          kind: "notice",
          title: "I can't store that yet",
          body: "Sentinel's memory forms on its own, when the same situation happens more than once — it can't yet take an instruction to remember something. What it has learned so far is on the memory page.",
          to: "/memory",
          toLabel: "See what Sentinel remembers",
        });
        return;

      default: {
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
    // The app shell owns scrolling, so this lays out in normal page flow and
    // pins the composer with `sticky` rather than fighting for its own scroll
    // container - which is also what keeps it usable on a phone.
    <div className="flex min-h-[calc(100vh-9rem)] gap-6">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="mb-5">
          <h1 className="text-h2 font-semibold tracking-tight text-ink">Assistant</h1>
          <p className="mt-1 text-small text-ink-dim">
            Ask about anything Sentinel watches — what happened, why it matters, what to do, or ask it
            to do something.
          </p>
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
                  memories={intel.memories}
                />
              ))}
            </div>
          ) : (
            /* The opening state names what it can actually do, rather than
               asking "how can I help?" - which puts the work of knowing what
               to ask on the person who came here to find out. */
            <div className="rounded-lg border border-border bg-surface p-5">
              <p className="text-small font-medium text-ink">What Sentinel can answer</p>
              <ul className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
                {CAPABILITIES.map((c) => (
                  <li key={c.label} className="flex items-start gap-2.5">
                    <Icon name={c.icon} size={14} className="mt-0.5 flex-none text-ink-faint" />
                    <span className="min-w-0">
                      <span className="block text-caption text-ink">{c.label}</span>
                      <span className="block text-micro text-ink-faint">{c.example}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
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

/** What the router actually supports, each with the phrasing it recognises.
 *  Listed rather than described, so the opening screen teaches the vocabulary
 *  instead of inviting an open-ended question it may not be able to answer. */
const CAPABILITIES: { label: string; example: string; icon: IconName }[] = [
  { label: "Catch up", example: "“What did I miss?”", icon: "activity" },
  { label: "Triage", example: "“What’s urgent?”", icon: "alert" },
  { label: "Investigate", example: "“What’s happening with …”", icon: "layers" },
  { label: "Prepare", example: "“Prepare me for my next meeting”", icon: "calendar" },
  { label: "Act", example: "“Create a task to …”", icon: "check" },
  { label: "Recall", example: "“What do you remember?”", icon: "brain" },
];

/* ------------------------------------------------------------ one turn -- */

function TurnView({
  turn,
  onResolve,
  onAsk,
  memories,
}: {
  turn: Turn;
  onResolve: (i: AttentionItem, s: "done" | "snoozed") => void;
  onAsk: (q: string) => void;
  memories: MemoryRow[];
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
            <Spinner size="sm" /> Checking with the Core…
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
                {b.gapHours < 48
                  ? `${Math.round(b.gapHours)} hours`
                  : `${Math.round(b.gapHours / 24)} days`}
                .
              </p>
            )}
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              <Chip onClick={() => onAsk("What's urgent?")}>What's urgent?</Chip>
              <Chip onClick={() => onAsk("What situations are open?")}>Show situations</Chip>
            </div>
          </>
        )}

        {b.kind === "attention" &&
          (b.items.length === 0 ? (
            <p className="text-small text-ink-dim">Nothing is open right now.</p>
          ) : (
            <>
              <p className="mb-2 text-small text-ink-dim">
                {b.items.length} thing{b.items.length === 1 ? "" : "s"}, most pressing first.
              </p>
              <AttentionRows items={b.items} onResolve={onResolve} />
            </>
          ))}

        {b.kind === "situations" && (
          <>
            <p className="mb-2 text-small text-ink-dim">
              {b.subject
                ? `${b.rows.length} situation${b.rows.length === 1 ? "" : "s"} matching “${b.subject}”.`
                : `${b.rows.length} open situation${b.rows.length === 1 ? "" : "s"}.`}
            </p>
            <ul className="flex flex-col gap-2">
              {b.rows.slice(0, 5).map((s) => (
                <li key={s.id}>
                  <SituationCard situation={s} />
                </li>
              ))}
            </ul>
          </>
        )}

        {b.kind === "memory" &&
          (memories.length === 0 ? (
            <p className="text-small text-ink-dim">
              Nothing yet. Memory forms when the same situation happens more than once.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {memories.slice(0, 5).map((m) => (
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

/**
 * propose -> confirm -> execute -> verify, in a card.
 *
 * Nothing here talks to a provider. Every step is an Action Registry call, and
 * the card cannot skip the confirmation: the server decides whether approval
 * is required and this only ever renders what it sent back.
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
        <p className="mb-2 text-small font-semibold capitalize text-ink">
          {(current.preview?.title as string) ?? current.action_type.replace(/_/g, " ")}
        </p>
        <dl className="flex flex-col gap-1.5">
          {Object.entries(fields).map(([k, v]) => (
            <div key={k} className="flex gap-3">
              <dt className="w-24 flex-none text-micro capitalize text-ink-faint">
                {k.replace(/_/g, " ")}
              </dt>
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
          <Badge tone="good">Done</Badge>
          {current.verification && (
            <span className="text-micro text-ink-faint">Verified: {current.verification}</span>
          )}
          {current.status === "unknown" && (
            <span className="text-micro text-warn">Applied, but Sentinel couldn't confirm it.</span>
          )}
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

/* ------------------------------------------------------------ fragments -- */

