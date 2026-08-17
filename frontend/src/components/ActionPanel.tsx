import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api/client";
import type { ActionCatalogEntry, ActionPolicy, SentinelAction } from "../api/types";

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
/** What an action should be called on screen.
 *
 *  The old fallback was `preview.title ?? action_type`, and most previews carry
 *  `summary` rather than `title` - so the history list rendered raw registry
 *  keys at the user: "todo.create_task", "zoom.create_meeting". The last resort
 *  now humanises the key instead of printing it, because a user should never
 *  have to read an identifier.
 */
function actionLabel(a: { preview?: Record<string, unknown>; action_type: string }): string {
  const preview = a.preview ?? {};
  for (const key of ["title", "summary"]) {
    const v = preview[key];
    if (typeof v === "string" && v.trim()) return v;
  }
  const [, verbNoun = a.action_type] = a.action_type.split(".");
  const words = verbNoun.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function ActionPanel({ scope, teamId }: { scope: "personal" | "channel"; teamId?: string }) {
  const [actions, setActions] = useState<SentinelAction[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [asking, setAsking] = useState(false);
  const [intentError, setIntentError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<ActionCatalogEntry[]>([]);
  const [showCatalog, setShowCatalog] = useState(false);
  const [policies, setPolicies] = useState<ActionPolicy[]>([]);

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

  async function undo(id: string) {
    setBusy(id);
    try {
      await api.post(`/actions/${id}/undo`);
      await load();
    } finally {
      setBusy(null);
    }
  }

  /** Plain text in, a *proposal* out. This never executes - the proposal
   *  appears above with its preview and still needs a decision. */
  async function ask() {
    if (text.trim().length < 3) return;
    setAsking(true);
    setIntentError(null);
    try {
      await api.post(`${path}/from-text`, { text: text.trim() });
      setText("");
      await load();
    } catch (e) {
      // Sentinel declining to guess is a normal outcome, not a failure.
      setIntentError(e instanceof ApiError ? e.message : "Sentinel couldn't interpret that");
    } finally {
      setAsking(false);
    }
  }

  async function openCatalog() {
    setShowCatalog((v) => !v);
    if (catalog.length === 0) {
      try {
        const [entries, current] = await Promise.all([
          api.get<ActionCatalogEntry[]>(`/actions/catalog?scope=${scope}`),
          // Personal policies only: a channel's are admin-managed and read
          // through the channel's own route.
          scope === "personal" ? api.get<ActionPolicy[]>("/actions/policy") : Promise.resolve([]),
        ]);
        setCatalog(entries);
        setPolicies(current);
      } catch {
        setCatalog([]);
      }
    }
  }

  /** Let one low-risk, fully reversible action run unattended.
   *
   *  Nothing currently runs on a schedule - this is the opt-in a future one
   *  would require, and it is off until a person turns it on. The server
   *  refuses anything the registry would never allow unattended, so this
   *  control cannot enable something unsafe even if it is shown by mistake. */
  async function toggleAutonomy(actionType: string, enabled: boolean) {
    setBusy(actionType);
    try {
      const policyPath = scope === "channel" ? `/teams/${teamId}/actions/policy` : "/actions/policy";
      await api.put(policyPath, { action_type: actionType, enabled, daily_limit: 5 });
      if (scope === "personal") setPolicies(await api.get<ActionPolicy[]>("/actions/policy"));
    } finally {
      setBusy(null);
    }
  }

  const pending = actions.filter((a) => a.status === "awaiting_approval");
  const history = actions.filter((a) => a.executed_at !== null).slice(0, 5);


  return (
    <div className="mb-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="label-sub font-bold text-ink-dim">🤖 Actions</span>
          <span className="rounded-full border border-border px-1.5 py-px text-micro text-ink-faint">
            {scope === "personal" ? "🔒 Private to you" : "👥 Shared with this channel"}
          </span>
        </div>
        <button
          onClick={openCatalog}
          className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
        >
          {showCatalog ? "Hide" : "What can Sentinel do?"}
        </button>
      </div>

      {/* Ask in plain words. Produces a proposal, never an action. */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void ask();
          }}
          placeholder={
            scope === "personal"
              ? "Ask Sentinel to do something — e.g. remind me to review the deck on Friday"
              : "Ask Sentinel to do something for this channel"
          }
          className="min-w-0 flex-1 rounded-md border border-border bg-transparent px-2.5 py-1.5 text-small outline-none focus:border-border-strong"
        />
        <button onClick={ask} disabled={asking || text.trim().length < 3} className="btn-primary">
          {asking ? "Thinking…" : "Propose"}
        </button>
      </div>
      <p className="mb-2 text-micro text-ink-faint">
        Sentinel will show you exactly what it plans to do. Nothing runs until you confirm.
      </p>
      {intentError && <p className="mb-2 text-caption text-crit">{intentError}</p>}

      {showCatalog && (
        <div className="mb-3 flex flex-col gap-1 rounded-md border border-border bg-surface p-3">
          {catalog.map((c) => {
            const policy = policies.find((p) => p.action_type === c.key);
            return (
              <div key={c.key} className="flex items-baseline justify-between gap-3 text-caption">
                <span className={c.available ? "text-ink-dim" : "text-ink-faint line-through"}>{c.label}</span>
                <span className="flex flex-none items-center gap-2 text-micro text-ink-faint">
                  {c.available
                    ? `${c.risk} risk · ${c.reversibility}${c.requires_channel_admin ? " · admin only" : ""}`
                    : c.unavailable_reason}
                  {/* Only offered where the registry says it could ever be
                      safe - low risk and fully reversible. */}
                  {c.available && c.autonomy_eligible && (
                    <label className="flex items-center gap-1 text-ink-faint">
                      <input
                        type="checkbox"
                        checked={Boolean(policy?.enabled)}
                        disabled={busy === c.key}
                        onChange={(e) => toggleAutonomy(c.key, e.target.checked)}
                        className="accent-current"
                      />
                      run unattended
                    </label>
                  )}
                </span>
              </div>
            );
          })}
          <p className="mt-1 text-micro leading-relaxed text-ink-faint">
            "Run unattended" is offered only for low-risk, fully reversible actions, and is off unless you turn it
            on. Nothing currently runs on a schedule — this is the permission a future one would need.
          </p>
        </div>
      )}

      {pending.map((a) => (
        <div key={a.id} className="mb-2 rounded-md border border-watch/40 bg-watch/5 p-3.5">
          <div className="label-sub mb-1 font-bold text-ink-dim">{actionLabel(a)}</div>

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
                  {actionLabel(a)}
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
                {/* Only offered where the registry says an inverse exists. */}
                {(a.status === "succeeded" || a.status === "unknown") && !a.undone_at && (
                  <button
                    onClick={() => undo(a.id)}
                    disabled={busy === a.id}
                    className="flex-none text-micro text-ink-faint underline underline-offset-2 hover:text-crit disabled:opacity-50"
                  >
                    Undo
                  </button>
                )}
                {a.undone_at && <span className="flex-none text-micro text-watch">Undone</span>}
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
