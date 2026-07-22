import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Situation } from "../api/types";
import { InvestigationPanel, useInvestigation } from "./InvestigationPanel";

const STATUS_COPY: Record<string, { label: string; tone: string }> = {
  emerging: { label: "Emerging", tone: "border-watch/40 bg-watch/5" },
  active: { label: "Developing", tone: "border-crit/40 bg-crit/5" },
};

/**
 * What Sentinel noticed without being asked.
 *
 * Sits above the attention list rather than inside it, because it answers a
 * different question: attention is "what arrived", this is "what several
 * signals add up to". It renders nothing at all when nothing qualifies -
 * an empty state here would be a permanent reminder of a feature rather
 * than a signal, and this surface is only worth having if it stays quiet.
 *
 * `scope` decides which world the reader is in and is shown explicitly: a
 * person looking at a situation must know whether it was assembled from
 * their own private context or from what their team shares.
 */
export function ProactiveStrip({ scope, teamId }: { scope: "personal" | "channel"; teamId?: string }) {
  const [situations, setSituations] = useState<Situation[]>([]);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [investigatingId, setInvestigatingId] = useState<string | null>(null);
  const investigation = useInvestigation();

  const path = scope === "channel" ? `/teams/${teamId}/proactive` : "/proactive";

  /** A situation is investigable in its own right - it already carries
   *  authorized evidence, which is all the investigation engine needs. The
   *  endpoint matches this strip's scope, so a channel situation is
   *  investigated as the channel and a private one as you. */
  function investigateFor(situationId: string) {
    if (investigatingId === situationId) {
      setInvestigatingId(null);
      investigation.clear();
      return;
    }
    setInvestigatingId(situationId);
    void investigation.load(`${path}/${situationId}/investigate`);
  }

  const load = useCallback(
    async (refresh = false) => {
      setBusy(true);
      try {
        setSituations(await api.get<Situation[]>(`${path}${refresh ? "?refresh=true" : ""}`));
      } catch {
        setSituations([]);
      } finally {
        setBusy(false);
      }
    },
    [path],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Silence is the correct output most days.
  if (situations.length === 0) return null;

  return (
    <div className="mb-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="label-sub font-bold text-ink-dim">Sentinel noticed</span>
          <span className="rounded-full border border-border px-1.5 py-px text-micro text-ink-faint">
            {scope === "personal" ? "🔒 Private to you" : "👥 Shared with this channel"}
          </span>
        </div>
        <button
          onClick={() => load(true)}
          disabled={busy}
          className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink disabled:opacity-50"
        >
          {busy ? "Checking…" : "↻ Check again"}
        </button>
      </div>

      {situations.map((s) => {
        const status = STATUS_COPY[s.status] ?? STATUS_COPY.emerging;
        const open = expanded === s.id;
        return (
          <div key={s.id} className={`rounded-md border p-3.5 ${status.tone}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="mb-0.5 flex items-center gap-2">
                  <span className="font-mono text-micro uppercase tracking-wide text-ink-faint">{status.label}</span>
                  <span className="text-micro text-ink-faint">
                    {s.evidence_count} signal{s.evidence_count === 1 ? "" : "s"} · since{" "}
                    {new Date(s.first_seen_at).toLocaleDateString()}
                  </span>
                </div>
                <div className="text-body font-semibold text-ink">{s.what_is_developing ?? s.title}</div>
                {s.why_it_matters && (
                  <p className="mt-1 text-small leading-relaxed text-ink-dim">{s.why_it_matters}</p>
                )}
              </div>
            </div>

            {s.suggested_next_steps.length > 0 && (
              <ul className="mt-2 flex flex-col gap-1">
                {s.suggested_next_steps.map((step) => (
                  <li key={step} className="text-small leading-relaxed text-ink-dim">
                    → {step}
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-2.5 flex flex-wrap items-center gap-3 text-caption">
              <button
                onClick={() => setExpanded(open ? null : s.id)}
                className="text-ink-faint underline underline-offset-2 hover:text-ink"
              >
                {open ? "Hide evidence" : `Show evidence (${s.evidence.length})`}
              </button>
              <button
                onClick={() => investigateFor(s.id)}
                disabled={investigation.loading && investigatingId === s.id}
                className={`underline underline-offset-2 disabled:opacity-50 ${
                  investigatingId === s.id ? "text-accent-text" : "text-ink-faint hover:text-ink"
                }`}
              >
                {investigation.loading && investigatingId === s.id ? "Investigating…" : "Investigate This ✨"}
              </button>
              <span className="text-micro text-ink-faint">
                confidence {Math.round(s.confidence * 100)}%
              </span>
            </div>

            {investigatingId === s.id && (investigation.investigation || investigation.error) && (
              <div className="mt-2">
                {investigation.error ? (
                  <p className="text-caption text-crit">{investigation.error}</p>
                ) : (
                  <InvestigationPanel
                    investigation={investigation.investigation!}
                    refreshing={investigation.refreshing}
                    onRefresh={() => investigation.load(`${path}/${s.id}/investigate`, { refresh: true })}
                    onClose={() => {
                      setInvestigatingId(null);
                      investigation.clear();
                    }}
                  />
                )}
              </div>
            )}

            {open && (
              <div className="mt-2 flex flex-col gap-1 border-t border-border pt-2">
                <div className="text-micro uppercase tracking-wide text-ink-faint">
                  What Sentinel actually saw
                </div>
                {s.evidence.map((e) => (
                  <a
                    key={e.signal_id}
                    href={e.url ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-2 rounded-md px-1.5 py-1 text-caption text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
                  >
                    <span className="flex-none text-micro text-ink-faint">
                      {e.occurred_at.slice(0, 10)}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{e.title}</span>
                  </a>
                ))}
                {/* The line between what was observed and what was concluded. */}
                <p className="mt-1 text-micro leading-relaxed text-ink-faint">
                  The signals above are facts retrieved from your connected data. The summary and next steps are
                  Sentinel's reading of them.
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
