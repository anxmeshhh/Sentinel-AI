import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { SentinelAction } from "../api/types";

const STATUS_COPY: Record<string, { label: string; tone: string }> = {
  awaiting_approval: { label: "Needs your approval", tone: "text-watch" },
  approved: { label: "Approved", tone: "text-ink-faint" },
  executing: { label: "Running", tone: "text-watch" },
  succeeded: { label: "Done", tone: "text-good" },
  failed: { label: "Failed", tone: "text-crit" },
  unknown: { label: "Unconfirmed", tone: "text-watch" },
  rejected: { label: "Declined", tone: "text-ink-faint" },
  cancelled: { label: "Cancelled", tone: "text-ink-faint" },
};

const RISK_COPY: Record<string, string> = {
  low: "reversible",
  medium: "changes something outside Sentinel",
  high: "high impact",
};

/**
 * Actions Sentinel wants to take, and what it did.
 *
 * The approval card is the whole point of this surface: before anything with
 * an external effect runs, a person sees exactly what will happen, to which
 * system, and why Sentinel suggested it. Nothing here executes without a
 * click, and the click is on a preview the server stored - not on text the
 * client re-rendered.
 *
 * Finished actions stay visible with their outcome, including the honest
 * middle state: "ran, but Sentinel could not confirm it" is shown as such
 * rather than being rounded to success or failure.
 */
export function ActionPanel({ scope, teamId }: { scope: "personal" | "channel"; teamId?: string }) {
  const [actions, setActions] = useState<SentinelAction[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const path = scope === "channel" ? `/teams/${teamId}/actions` : "/actions";

  const load = useCallback(async () => {
    try {
      setActions(await api.get<SentinelAction[]>(path));
    } catch {
      setActions([]);
    }
  }, [path]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(id: string, verb: "approve" | "reject" | "execute") {
    setBusy(id);
    try {
      if (verb === "approve") {
        // Approve then run, so one click means one completed decision - but
        // they remain separate server calls, and the server enforces the
        // order regardless of what the client does.
        await api.post(`/actions/${id}/approve`);
        await api.post(`/actions/${id}/execute`);
      } else {
        await api.post(`/actions/${id}/${verb}`);
      }
      await load();
    } finally {
      setBusy(null);
    }
  }

  const pending = actions.filter((a) => a.status === "awaiting_approval");
  const history = actions.filter((a) => a.executed_at !== null).slice(0, 5);

  if (pending.length === 0 && history.length === 0) return null;

  return (
    <div className="mb-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="label-sub font-bold text-ink-dim">🤖 Actions</span>
        <span className="rounded-full border border-border px-1.5 py-px text-micro text-ink-faint">
          {scope === "personal" ? "🔒 Private to you" : "👥 Shared with this channel"}
        </span>
      </div>

      {pending.map((a) => (
        <div key={a.id} className="mb-2 rounded-md border border-watch/40 bg-watch/5 p-3.5">
          <div className="label-sub mb-1 font-bold text-ink-dim">{a.preview.title ?? a.action_type}</div>

          {/* Exactly what will happen, field by field. */}
          <div className="mb-2 flex flex-col gap-0.5">
            {Object.entries(a.preview.fields ?? {}).map(([k, v]) => (
              <div key={k} className="flex gap-2 text-caption">
                <span className="w-20 flex-none text-ink-faint">{k}</span>
                <span className="min-w-0 flex-1 text-ink-dim">{String(v)}</span>
              </div>
            ))}
          </div>

          {/* What leaves Sentinel, stated plainly. */}
          {a.preview.effect && (
            <p className="mb-2 text-caption leading-relaxed text-ink-dim">{a.preview.effect}</p>
          )}

          {/* Why Sentinel suggested it at all. */}
          {a.reason && <p className="mb-2 text-caption leading-relaxed text-ink-faint">Why: {a.reason}</p>}

          <div className="flex flex-wrap items-center gap-3 text-caption">
            <button onClick={() => act(a.id, "approve")} disabled={busy === a.id} className="btn-primary">
              {busy === a.id ? "Working…" : "Confirm"}
            </button>
            <button
              onClick={() => act(a.id, "reject")}
              disabled={busy === a.id}
              className="text-ink-faint underline underline-offset-2 hover:text-crit disabled:opacity-50"
            >
              Cancel
            </button>
            <span className="text-micro text-ink-faint">{RISK_COPY[a.risk] ?? a.risk}</span>
          </div>
        </div>
      ))}

      {history.length > 0 && (
        <div className="flex flex-col gap-1">
          {history.map((a) => {
            const status = STATUS_COPY[a.status] ?? STATUS_COPY.unknown;
            return (
              <div key={a.id} className="flex items-baseline justify-between gap-3 text-caption">
                <span className="min-w-0 flex-1 truncate text-ink-dim">
                  {a.preview.title ?? a.action_type}
                  {Boolean(a.result?.url) && (
                    <a
                      href={String(a.result.url)}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-2 text-accent-text hover:underline"
                    >
                      open
                    </a>
                  )}
                </span>
                <span className={`flex-none font-mono text-micro uppercase tracking-wide ${status.tone}`}>
                  {status.label}
                </span>
              </div>
            );
          })}
          {/* The honest middle state, explained where it appears. */}
          {history.some((a) => a.status === "unknown") && (
            <p className="mt-1 text-micro leading-relaxed text-ink-faint">
              "Unconfirmed" means Sentinel made the change but could not read it back to verify. It may well have
              worked — check before repeating it.
            </p>
          )}
          {history.some((a) => a.status === "failed") && (
            <p className="mt-1 text-micro leading-relaxed text-crit">
              {String(history.find((a) => a.status === "failed")?.error ?? "")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
