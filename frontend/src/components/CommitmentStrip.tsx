import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Commitment } from "../api/types";
import { InvestigationPanel, useInvestigation } from "./InvestigationPanel";
import { Button } from "./ui";

const STATUS_COPY: Record<string, { label: string; tone: string; border: string }> = {
  // A suggestion is a question, so it is styled as one - quiet, not alarming.
  suggested: { label: "Possible commitment", tone: "text-ink-faint", border: "border-dashed border-border bg-surface" },
  overdue: { label: "Overdue", tone: "text-crit", border: "border-crit/40 bg-crit/5" },
  at_risk: { label: "At risk", tone: "text-crit", border: "border-crit/30 bg-crit/[0.04]" },
  due_soon: { label: "Due soon", tone: "text-watch", border: "border-watch/40 bg-watch/5" },
  pending: { label: "Tracking", tone: "text-ink-faint", border: "border-border bg-surface" },
};

function whenCopy(due: string | null): string {
  if (!due) return "no date";
  const date = new Date(due);
  const hours = (date.getTime() - Date.now()) / 3600000;
  if (hours < -24) return `${Math.round(-hours / 24)}d overdue`;
  if (hours < 0) return "overdue";
  if (hours < 24) return `in ${Math.max(1, Math.round(hours))}h`;
  return date.toLocaleDateString();
}

/**
 * What was promised, and whether it is actually happening.
 *
 * Deliberately not a task board. Every row answers the same five questions -
 * what, who, when, status, and why Sentinel is tracking it - and nothing
 * else. A commitment Sentinel derived from a signal shows that signal as
 * evidence; one a person stated shows that it was stated.
 *
 * Renders nothing when there is nothing outstanding, apart from the way to
 * add one.
 */
export function CommitmentStrip({ scope, teamId }: { scope: "personal" | "channel"; teamId?: string }) {
  const [commitments, setCommitments] = useState<Commitment[]>([]);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [investigatingId, setInvestigatingId] = useState<string | null>(null);
  const investigation = useInvestigation();
  const [what, setWhat] = useState("");
  const [due, setDue] = useState("");

  const path = scope === "channel" ? `/teams/${teamId}/commitments` : "/commitments";

  const load = useCallback(
    async (refresh = false) => {
      try {
        setCommitments(
          await api.get<Commitment[]>(`${path}?include_closed=true${refresh ? "&refresh=true" : ""}`),
        );
      } catch {
        setCommitments([]);
      }
    },
    [path],
  );

  useEffect(() => {
    void load(true);
  }, [load]);

  async function act(id: string, action: "resolve" | "dismiss" | "confirm" | "reopen") {
    setBusy(true);
    try {
      await api.post(`/commitments/${id}/${action}`, action === "resolve" ? { reason: "Marked done" } : undefined);
      await load();
    } finally {
      setBusy(false);
    }
  }

  /** A commitment is its own investigation anchor - "we said this would
   *  happen and it hasn't" is the most useful thing to expand evidence
   *  around. The endpoint derives scope from the commitment itself. */
  function investigateFor(id: string) {
    if (investigatingId === id) {
      setInvestigatingId(null);
      investigation.clear();
      return;
    }
    setInvestigatingId(id);
    void investigation.load(`/commitments/${id}/investigate`);
  }

  async function add() {
    if (what.trim().length < 2) return;
    setBusy(true);
    try {
      await api.post(path, { what: what.trim(), due_at: due ? new Date(due).toISOString() : null });
      setWhat("");
      setDue("");
      setAdding(false);
      await load();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="label-sub font-bold text-ink-dim">Commitments</span>
          <span className="rounded-full border border-border px-1.5 py-px text-micro text-ink-faint">
            {scope === "personal" ? "🔒 Private to you" : "👥 Shared with this channel"}
          </span>
        </div>
        <Button size="sm" variant="ghost" onClick={() => setAdding((v) => !v)}>
          {adding ? "Cancel" : "+ Track something"}
        </Button>
      </div>

      {adding && (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface p-3">
          <input
            value={what}
            onChange={(e) => setWhat(e.target.value)}
            placeholder={scope === "personal" ? "Send the report" : "We'll ship the revised proposal"}
            className="min-w-0 flex-1 rounded-md border border-border bg-transparent px-2 py-1.5 text-small outline-none focus:border-border-strong"
          />
          <input
            type="date"
            value={due}
            onChange={(e) => setDue(e.target.value)}
            className="rounded-md border border-border bg-transparent px-2 py-1.5 text-caption text-ink-dim outline-none focus:border-border-strong"
          />
          <Button size="sm" variant="primary" onClick={add} disabled={busy}>
            Track
          </Button>
        </div>
      )}

      {commitments.length === 0 ? (
        <p className="text-caption text-ink-faint">
          Nothing outstanding{scope === "channel" ? " for this channel" : ""}.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {commitments.map((c) => {
            const status = STATUS_COPY[c.status] ?? STATUS_COPY.pending;
            return (
              <div key={c.id} className={`rounded-md border p-3 ${status.border}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-small font-semibold text-ink">{c.what}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-micro text-ink-faint">
                      <span className={`font-mono uppercase tracking-wide ${status.tone}`}>{status.label}</span>
                      {c.owner_label && <span>· {c.owner_label}</span>}
                      <span>· {whenCopy(c.due_at)}</span>
                      {/* Why Sentinel is tracking it, stated rather than implied. */}
                      <span>
                        ·{" "}
                        {c.source === "manual"
                          ? "you tracked this"
                          : c.source === "extracted"
                            ? "read from a message"
                            : "from a tracked issue"}
                      </span>
                    </div>
                  </div>
                  <div className="flex flex-none items-center gap-2.5 text-caption">
                    {c.status === "suggested" ? (
                      <>
                        <Button size="sm" variant="secondary" onClick={() => act(c.id, "confirm")} disabled={busy}>
                          Track this
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => act(c.id, "dismiss")} disabled={busy}>
                          No thanks
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button size="sm" variant="secondary" onClick={() => investigateFor(c.id)} disabled={busy || (investigation.loading && investigatingId === c.id)}>
                          {investigation.loading && investigatingId === c.id ? "Investigating…" : "Investigate ✨"}
                        </Button>
                        <Button size="sm" variant="secondary" onClick={() => act(c.id, "resolve")} disabled={busy}>
                          Done
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => act(c.id, "dismiss")} disabled={busy}>
                          Dismiss
                        </Button>
                      </>
                    )}
                    {(c.status === "resolved" || c.status === "dismissed") && (
                      <Button size="sm" variant="secondary" onClick={() => act(c.id, "reopen")} disabled={busy}>
                        Reopen
                      </Button>
                    )}
                  </div>
                </div>

                {/* Sentinel asking, rather than asserting. */}
                {c.status === "suggested" && (
                  <p className="mt-1.5 text-caption leading-relaxed text-ink-faint">
                    Sentinel noticed a possible commitment in a message — track this?
                  </p>
                )}

                {investigatingId === c.id && (investigation.investigation || investigation.error) && (
                  <div className="mt-2">
                    {investigation.error ? (
                      <p className="text-caption text-crit">{investigation.error}</p>
                    ) : (
                      <InvestigationPanel
                        investigation={investigation.investigation!}
                        refreshing={investigation.refreshing}
                        onRefresh={() => investigation.load(`/commitments/${c.id}/investigate`, { refresh: true })}
                        onClose={() => {
                          setInvestigatingId(null);
                          investigation.clear();
                        }}
                      />
                    )}
                  </div>
                )}

                {c.evidence.length > 0 && (
                  <div className="mt-1.5 flex flex-col gap-1 border-t border-border pt-1.5">
                    {c.evidence.map((e) => (
                      <a
                        key={e.signal_id}
                        href={e.url ?? undefined}
                        target="_blank"
                        rel="noreferrer"
                        className="truncate text-caption text-ink-dim hover:text-ink hover:underline"
                      >
                        {e.title}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
