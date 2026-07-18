import { useState } from "react";

import { api, ApiError } from "../api/client";

type TurnStatus = "done" | "confirmation_required" | "executing" | "executed" | "error" | "cancelled";

interface PendingAction {
  name: string;
  arguments: Record<string, unknown>;
}

interface Turn {
  command: string;
  status: TurnStatus;
  reply?: string | null;
  plan?: Record<string, unknown> | null;
  pendingAction?: PendingAction | null;
  executedResult?: Record<string, unknown> | null;
}

interface CommandResponse {
  status: TurnStatus;
  reply: string | null;
  plan: Record<string, unknown> | null;
  pending_action: PendingAction | null;
}

export function GoogleAICommand() {
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [sending, setSending] = useState(false);

  async function send() {
    const command = input.trim();
    if (!command || sending) return;
    setSending(true);
    setInput("");
    try {
      const res = await api.post<CommandResponse>("/connections/google/command", { command });
      setTurns((t) => [...t, { command, status: res.status, reply: res.reply, plan: res.plan, pendingAction: res.pending_action }]);
    } catch (err) {
      setTurns((t) => [...t, { command, status: "error", reply: err instanceof ApiError ? err.message : "Something went wrong." }]);
    } finally {
      setSending(false);
    }
  }

  async function confirmAction(index: number) {
    const turn = turns[index];
    if (!turn.pendingAction) return;
    setTurns((t) => t.map((x, i) => (i === index ? { ...x, status: "executing" } : x)));
    try {
      const res = await api.post<{ result: Record<string, unknown> }>("/connections/google/command/execute", turn.pendingAction);
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
      <div className="mb-1 text-[11.5px] font-semibold text-ink-dim">AI Command</div>
      <p className="mb-3 text-[11px] leading-relaxed text-ink-faint">
        Ask across Gmail + Calendar together — e.g. "summarize my important emails and schedule a follow-up
        meeting." Actions that change anything (like creating an event) are shown as a plan you confirm first,
        never run automatically.
      </p>

      {turns.length > 0 && (
        <div className="mb-3 flex flex-col gap-2.5">
          {turns.map((turn, i) => (
            <div key={i} className="rounded-md border border-border bg-ground/40 p-3">
              <div className="mb-1.5 text-[12px] font-semibold text-ink">{turn.command}</div>

              {turn.status === "done" && <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-ink-dim">{turn.reply}</p>}
              {turn.status === "error" && <p className="text-[12px] text-crit">{turn.reply ?? "Something went wrong."}</p>}
              {turn.status === "cancelled" && <p className="text-[12px] text-ink-faint">Cancelled — nothing was changed.</p>}

              {(turn.status === "confirmation_required" || turn.status === "executing") && turn.plan && (
                <div className="rounded-md border border-watch/40 bg-watch/5 p-2.5">
                  <div className="mb-1.5 font-mono text-[10.5px] font-bold uppercase tracking-wide text-watch">
                    Sentinel plans to:
                  </div>
                  <PlanDetails plan={turn.plan} />
                  <div className="mt-2.5 flex gap-2">
                    <button
                      onClick={() => confirmAction(i)}
                      disabled={turn.status === "executing"}
                      className="rounded-md bg-accent px-3 py-1.5 font-mono text-[11px] font-bold text-ground disabled:opacity-50"
                    >
                      {turn.status === "executing" ? "Executing…" : "Confirm & Execute"}
                    </button>
                    <button
                      onClick={() => cancelAction(i)}
                      disabled={turn.status === "executing"}
                      className="rounded-md border border-border px-3 py-1.5 font-mono text-[11px] text-ink-dim hover:border-crit hover:text-crit disabled:opacity-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {turn.status === "executed" && turn.executedResult && (
                <div className="rounded-md border border-good/40 bg-good/5 p-2.5 text-[12px] text-good">
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
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Try: what are my most important unread emails?"
          className="flex-1 rounded-md border border-border bg-ground px-3 py-2 text-[12.5px] outline-none focus:border-accent"
        />
        <button
          onClick={send}
          disabled={sending || !input.trim()}
          className="rounded-md bg-accent px-3.5 py-2 font-mono text-[11.5px] font-bold text-ground disabled:opacity-50"
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
    <div className="flex flex-col gap-1 text-[11.5px]">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="w-24 flex-none capitalize text-ink-faint">{k.replace(/_/g, " ")}</span>
          <span className="text-ink-dim">{Array.isArray(v) ? (v.length ? v.join(", ") : "—") : String(v)}</span>
        </div>
      ))}
    </div>
  );
}
