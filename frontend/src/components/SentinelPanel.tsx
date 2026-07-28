import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import { Markdown } from "./Markdown";
import { Icon, Spinner, cn } from "./ui";
import { ContextBar } from "./ContextBar";
import type { ContextIdentity } from "./context";

/**
 * The one Sentinel AI surface.
 *
 * Every context - Google workspace, a single service, a Drive file, an
 * attention item, a Channel - renders this same component; only the
 * endpoint and the context label change. The orchestrator behind it is
 * already shared, so the UI must be too, or "Gmail AI" and "Channel AI"
 * quietly drift into different products.
 *
 * What this fixes over the old embedded command box, per the diagnosis:
 * - The retrieval trail accumulates instead of replacing itself, so a
 *   four-tool run reads as four visible steps, not a mutating spinner.
 * - Sources arrive as data (backend `sources` field) and render as a
 *   navigable block, instead of hoping the model linked things in prose.
 * - An empty panel teaches by example: contextual suggestions, not a blank
 *   input.
 *
 * The confirm-first safety model is untouched: a write action renders as a
 * plan, and nothing executes until the user clicks Confirm.
 */

type TurnStatus = "streaming" | "done" | "confirmation_required" | "executing" | "executed" | "error" | "cancelled";

interface PendingAction {
  name: string;
  arguments: Record<string, unknown>;
}

export interface AISource {
  kind: string;
  title: string;
  meta: string | null;
  url: string;
}

interface Turn {
  command: string;
  status: TurnStatus;
  /** Every status message seen so far - the visible retrieval trail. */
  trail: string[];
  reply?: string | null;
  plan?: Record<string, unknown> | null;
  pendingAction?: PendingAction | null;
  sources?: AISource[];
  executedResult?: Record<string, unknown> | null;
}

type StreamEvent =
  | { type: "status"; message: string }
  | {
      type: "result";
      status: TurnStatus;
      reply?: string | null;
      plan?: Record<string, unknown> | null;
      pending_action?: PendingAction | null;
      sources?: AISource[];
    };

const SOURCE_KIND_LABEL: Record<string, string> = {
  email: "Email",
  event: "Event",
  meeting: "Meeting",
  file: "File",
  repo: "Repo",
};

export interface SuggestionGroup {
  label: string;
  prompts: string[];
}

export function SentinelPanel({
  contextLabel,
  identity,
  endpointBase = "/connections/google",
  contextPrefix,
  placeholder,
  suggestions = [],
  suggestionGroups,
  header,
}: {
  /** Shown as "Using: …" - the user must never wonder what Sentinel can see. */
  contextLabel: string;
  /** The full context identity. When supplied the panel renders the
   *  persistent context bar (icon + world + PRIVATE/SHARED + what Sentinel
   *  may use) above the input, so the answer is visible before sending. */
  identity?: ContextIdentity;
  endpointBase?: string;
  /** Hidden context prepended to the request (e.g. which Drive file this is about). */
  contextPrefix?: string;
  placeholder?: string;
  /** Example prompts for the empty state - contextual, clickable. */
  suggestions?: string[];
  /** Grouped example prompts (e.g. GitHub's Repository Health / Development /
   *  Insights). When provided, rendered as labelled groups instead of a flat
   *  list. Same interaction, richer taxonomy - so a provider with many
   *  capabilities can organise them without a different component. */
  suggestionGroups?: SuggestionGroup[];
  /** Optional extra header content (e.g. a collapse button from the parent). */
  header?: ReactNode;
}) {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sending, setSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the newest turn in view as it streams.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turns]);

  async function send(text?: string) {
    const question = (text ?? input).trim();
    if (!question || sending) return;
    setSending(true);
    setInput("");

    const command = contextPrefix ? `${contextPrefix} ${question}` : question;
    const index = turns.length;
    setTurns((t) => [...t, { command: question, status: "streaming", trail: [] }]);

    try {
      await api.postStream(`${endpointBase}/command/stream`, { command }, (raw) => {
        const event = raw as StreamEvent;
        if (event.type === "status") {
          setTurns((t) => t.map((x, i) => (i === index ? { ...x, trail: [...x.trail, event.message] } : x)));
        } else if (event.type === "result") {
          setTurns((t) =>
            t.map((x, i) =>
              i === index
                ? {
                    ...x,
                    status: event.status,
                    reply: event.reply,
                    plan: event.plan,
                    pendingAction: event.pending_action,
                    sources: event.sources ?? [],
                  }
                : x,
            ),
          );
        }
      });
    } catch (err) {
      setTurns((t) =>
        t.map((x, i) =>
          i === index ? { ...x, status: "error", reply: err instanceof ApiError ? err.message : "Something went wrong." } : x,
        ),
      );
    } finally {
      setSending(false);
    }
  }

  async function confirmAction(index: number) {
    const turn = turns[index];
    if (!turn.pendingAction) return;
    setTurns((t) => t.map((x, i) => (i === index ? { ...x, status: "executing" } : x)));
    try {
      const res = await api.post<{ result: Record<string, unknown> }>(`${endpointBase}/command/execute`, turn.pendingAction);
      setTurns((t) => t.map((x, i) => (i === index ? { ...x, status: "executed", executedResult: res.result } : x)));
    } catch (err) {
      setTurns((t) =>
        t.map((x, i) =>
          i === index ? { ...x, status: "error", reply: err instanceof ApiError ? err.message : "Failed to execute." } : x,
        ),
      );
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Context header - what Sentinel can currently see, always visible. */}
      <div className="flex flex-none items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="relative h-[18px] w-[18px] flex-none rounded-full border border-ink" aria-hidden="true">
            <span className="absolute inset-[5px] rounded-full bg-brand" />
          </span>
          <div className="min-w-0">
            <div className="text-small font-semibold text-ink">Sentinel</div>
            {!identity && (
              <div className="truncate text-micro text-ink-faint">
                Using: <span className="text-ink-dim">{contextLabel}</span>
              </div>
            )}
          </div>
        </div>
        {header}
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {turns.length === 0 ? (
          <EmptyState contextLabel={contextLabel} suggestions={suggestions} suggestionGroups={suggestionGroups} onPick={(s) => void send(s)} />
        ) : (
          <div className="flex flex-col gap-5">
            {turns.map((turn, i) => (
              <TurnView key={i} turn={turn} onConfirm={() => confirmAction(i)} onCancel={() => setTurns((t) => t.map((x, j) => (j === i ? { ...x, status: "cancelled" } : x)))} />
            ))}
          </div>
        )}
      </div>

      {identity && <ContextBar identity={identity} className="flex-none border-t" />}

      <div className="flex flex-none gap-2 border-t border-border p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !sending && void send()}
          disabled={sending}
          placeholder={placeholder ?? `Ask about ${contextLabel}…`}
          className="min-w-0 flex-1 rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
        />
        <button onClick={() => void send()} disabled={sending || !input.trim()} className="btn-primary" aria-label="Send">
          {sending ? <Spinner size="sm" className="border-ground border-t-transparent" /> : <Icon name="arrowRight" size={15} />}
        </button>
      </div>
    </div>
  );
}

function SuggestionButton({ prompt, onPick }: { prompt: string; onPick: (s: string) => void }) {
  return (
    <button
      onClick={() => onPick(prompt)}
      className="w-full rounded-md border border-border px-3 py-2 text-left text-caption text-ink-dim transition-colors hover:border-border-strong hover:text-ink"
    >
      {prompt}
    </button>
  );
}

function EmptyState({
  contextLabel,
  suggestions,
  suggestionGroups,
  onPick,
}: {
  contextLabel: string;
  suggestions: string[];
  suggestionGroups?: SuggestionGroup[];
  onPick: (s: string) => void;
}) {
  const grouped = suggestionGroups && suggestionGroups.length > 0;
  return (
    <div className="flex h-full flex-col items-start justify-end gap-4 pb-2">
      <p className="text-caption leading-relaxed text-ink-faint">
        Sentinel can only see what's authorized in <span className="text-ink-dim">{contextLabel}</span>. Anything that
        would change your data is shown as a plan you confirm first.
      </p>
      {grouped ? (
        <div className="flex w-full flex-col gap-3.5">
          {suggestionGroups!.map((g) => (
            <div key={g.label} className="flex w-full flex-col gap-1.5">
              <div className="text-micro font-medium uppercase tracking-wide text-ink-faint">{g.label}</div>
              {g.prompts.map((p) => (
                <SuggestionButton key={p} prompt={p} onPick={onPick} />
              ))}
            </div>
          ))}
        </div>
      ) : (
        suggestions.length > 0 && (
          <div className="flex w-full flex-col gap-1.5">
            {suggestions.map((s) => (
              <SuggestionButton key={s} prompt={s} onPick={onPick} />
            ))}
          </div>
        )
      )}
    </div>
  );
}

function TurnView({ turn, onConfirm, onCancel }: { turn: Turn; onConfirm: () => void; onCancel: () => void }) {
  const streaming = turn.status === "streaming";
  return (
    <div>
      {/* The user's request - right-aligned so the conversation has sides. */}
      <div className="mb-2.5 flex justify-end">
        <div className="max-w-[90%] rounded-md bg-surface-2 px-3 py-2 text-small text-ink">{turn.command}</div>
      </div>

      {/* Retrieval trail: every step stays visible. Past steps check off;
          only the newest spins. A four-tool run should read as four things
          that happened, not one mutating message. */}
      {turn.trail.length > 0 && (streaming || turn.trail.length > 1) && (
        <div className="mb-2.5 flex flex-col gap-1 border-l border-rule-strong pl-3">
          {turn.trail.map((message, i) => {
            const isLive = streaming && i === turn.trail.length - 1;
            return (
              <div key={i} className={cn("flex items-center gap-2 text-caption", isLive ? "text-ink-dim" : "text-ink-faint")}>
                {isLive ? (
                  <Spinner size="sm" />
                ) : (
                  <Icon name="check" size={12} className="text-good/70" />
                )}
                {message}
              </div>
            );
          })}
        </div>
      )}

      {turn.status === "done" && turn.reply && (
        <div className="text-small leading-relaxed text-ink-dim">
          <Markdown text={turn.reply} />
        </div>
      )}

      {turn.status === "error" && (
        <div className="rounded-md border border-crit/30 bg-crit/5 px-3 py-2 text-caption text-crit">
          {turn.reply ?? "Something went wrong."} <span className="text-crit/70">Nothing was changed.</span>
        </div>
      )}
      {turn.status === "cancelled" && <p className="text-caption text-ink-faint">Cancelled — nothing was changed.</p>}

      {(turn.status === "confirmation_required" || turn.status === "executing") && turn.plan && (
        <div className="rounded-md border border-watch/40 bg-watch/5 p-3">
          <div className="label-sub mb-2 font-bold text-watch">Sentinel plans to:</div>
          <PlanDetails plan={turn.plan} />
          <div className="mt-3 flex gap-2">
            <button onClick={onConfirm} disabled={turn.status === "executing"} className="btn-primary">
              {turn.status === "executing" ? "Executing…" : "Confirm & Execute"}
            </button>
            <button
              onClick={onCancel}
              disabled={turn.status === "executing"}
              className="rounded-md border border-border px-3 py-1.5 text-caption text-ink-dim transition-colors hover:border-crit hover:text-crit disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {turn.status === "executed" && turn.executedResult && (
        <div className="rounded-md border border-good/40 bg-good/5 px-3 py-2 text-caption text-good">
          Done — event created{turn.executedResult.meet_link ? " with a Meet link" : ""}.
          {typeof turn.executedResult.url === "string" && (
            <>
              {" "}
              <a href={turn.executedResult.url} target="_blank" rel="noreferrer" className="underline underline-offset-2">
                Open in Calendar
              </a>
            </>
          )}
        </div>
      )}

      {/* Sources: structured citations from the tools that actually ran. */}
      {turn.sources && turn.sources.length > 0 && turn.status !== "streaming" && (
        <div className="mt-3">
          <div className="label-sub mb-1.5">Sources</div>
          <div className="flex flex-col gap-1">
            {turn.sources.map((source) => (
              <a
                key={source.url}
                href={source.url}
                target="_blank"
                rel="noreferrer"
                className="group flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5 transition-colors hover:border-border-strong"
              >
                <span className="flex-none rounded-sm border border-rule-strong px-1.5 py-px font-mono text-micro text-ink-faint">
                  {SOURCE_KIND_LABEL[source.kind] ?? source.kind}
                </span>
                <span className="min-w-0 flex-1 truncate text-caption text-ink-dim group-hover:text-ink">{source.title}</span>
                {source.meta && <span className="hidden flex-none truncate text-micro text-ink-faint sm:block sm:max-w-[35%]">{source.meta}</span>}
                <Icon name="external" size={12} className="flex-none text-ink-faint" />
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PlanDetails({ plan }: { plan: Record<string, unknown> }) {
  const entries = Object.entries(plan).filter(([k]) => k !== "action");
  return (
    <div className="flex flex-col gap-1 text-caption">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="w-24 flex-none capitalize text-ink-faint">{k.replace(/_/g, " ")}</span>
          <span className="text-ink-dim">{Array.isArray(v) ? (v.length ? v.join(", ") : "—") : String(v)}</span>
        </div>
      ))}
    </div>
  );
}
