import type { ReactNode } from "react";
import { useState } from "react";

import { api, ApiError } from "../api/client";
import { Markdown } from "./Markdown";

type TurnStatus = "streaming" | "done" | "confirmation_required" | "executing" | "executed" | "error" | "cancelled";

interface PendingAction {
  name: string;
  arguments: Record<string, unknown>;
}

interface Turn {
  command: string;
  status: TurnStatus;
  statusMessage?: string;
  reply?: string | null;
  plan?: Record<string, unknown> | null;
  pendingAction?: PendingAction | null;
  executedResult?: Record<string, unknown> | null;
}

type StreamEvent =
  | { type: "status"; message: string }
  | { type: "result"; status: TurnStatus; reply?: string | null; plan?: Record<string, unknown> | null; pending_action?: PendingAction | null };

export function GoogleAICommand({
  contextPrefix,
  placeholder,
  endpointBase = "/connections/google",
  helpText,
}: {
  contextPrefix?: string;
  placeholder?: string;
  /** Lets Channel AI (Phase 2m/2n) reuse this exact streaming/confirm UI
   * against /teams/{id}/ai instead of the original /connections/google -
   * same loop, same safety model, just a different scope on the backend. */
  endpointBase?: string;
  helpText?: ReactNode;
}) {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sending, setSending] = useState(false);

  async function send() {
    const question = input.trim();
    if (!question || sending) return;
    setSending(true);
    setInput("");

    // The displayed bubble shows just what the user typed; the actual
    // request sent to the model can carry hidden context (e.g. which
    // Drive file this question is "about") without cluttering the UI.
    const command = contextPrefix ? `${contextPrefix} ${question}` : question;
    const index = turns.length;
    setTurns((t) => [...t, { command: question, status: "streaming", statusMessage: "Starting…" }]);

    try {
      await api.postStream(`${endpointBase}/command/stream`, { command }, (raw) => {
        const event = raw as StreamEvent;
        if (event.type === "status") {
          setTurns((t) => t.map((x, i) => (i === index ? { ...x, statusMessage: event.message } : x)));
        } else if (event.type === "result") {
          setTurns((t) =>
            t.map((x, i) =>
              i === index
                ? { ...x, status: event.status, reply: event.reply, plan: event.plan, pendingAction: event.pending_action }
                : x
            )
          );
        }
      });
    } catch (err) {
      setTurns((t) =>
        t.map((x, i) => (i === index ? { ...x, status: "error", reply: err instanceof ApiError ? err.message : "Something went wrong." } : x))
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
        t.map((x, i) => (i === index ? { ...x, status: "error", reply: err instanceof ApiError ? err.message : "Failed to execute." } : x))
      );
    }
  }

  function cancelAction(index: number) {
    setTurns((t) => t.map((x, i) => (i === index ? { ...x, status: "cancelled" } : x)));
  }

  return (
    <div className="border-t border-border p-3.5">
      <div className="mb-1 text-caption font-semibold text-ink-dim">AI Command</div>
      <p className="mb-3 text-caption leading-relaxed text-ink-faint">
        {helpText ?? (
          <>
            Ask across Gmail + Calendar together — e.g. "summarize my important emails and schedule a follow-up
            meeting." Actions that change anything (like creating an event) are shown as a plan you confirm first,
            never run automatically.
          </>
        )}
      </p>

      {turns.length > 0 && (
        <div className="mb-3 flex flex-col gap-2.5">
          {turns.map((turn, i) => (
            <div key={i} className="rounded-md border border-border bg-ground/40 p-3">
              <div className="mb-1.5 text-small font-semibold text-ink">{turn.command}</div>

              {turn.status === "streaming" && (
                <div className="flex items-center gap-2 text-small text-ink-faint">
                  <span className="h-3 w-3 flex-none animate-spin rounded-full border-2 border-ink-faint border-t-transparent" />
                  {turn.statusMessage ?? "Working…"}
                </div>
              )}

              {turn.status === "done" && turn.reply && (
                <div className="text-small leading-relaxed text-ink-dim">
                  <Markdown text={turn.reply} />
                </div>
              )}
              {turn.status === "error" && <p className="text-small text-crit">{turn.reply ?? "Something went wrong."}</p>}
              {turn.status === "cancelled" && <p className="text-small text-ink-faint">Cancelled — nothing was changed.</p>}

              {(turn.status === "confirmation_required" || turn.status === "executing") && turn.plan && (
                <div className="rounded-md border border-watch/40 bg-watch/5 p-2.5">
                  <div className="label-sub mb-1.5 font-bold text-watch">
                    Sentinel plans to:
                  </div>
                  <PlanDetails plan={turn.plan} />
                  <div className="mt-2.5 flex gap-2">
                    <button
                      onClick={() => confirmAction(i)}
                      disabled={turn.status === "executing"}
                      className="btn-primary"
                    >
                      {turn.status === "executing" ? "Executing…" : "Confirm & Execute"}
                    </button>
                    <button
                      onClick={() => cancelAction(i)}
                      disabled={turn.status === "executing"}
                      className="rounded-md border border-border px-3 py-1.5 text-caption text-ink-dim hover:border-crit hover:text-crit disabled:opacity-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {turn.status === "executed" && turn.executedResult && (
                <div className="rounded-md border border-good/40 bg-good/5 p-2.5 text-small text-good">
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
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !sending && send()}
          disabled={sending}
          placeholder={placeholder ?? "Try: what are my most important unread emails?"}
          className="flex-1 rounded-md border border-border bg-ground px-3 py-2 text-small outline-none focus:border-accent focus:ring-2 focus:ring-accent/25 disabled:opacity-60"
        />
        <button
          onClick={send}
          disabled={sending || !input.trim()}
          className="btn-primary"
        >
          {sending ? "…" : "Send"}
        </button>
      </div>
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
