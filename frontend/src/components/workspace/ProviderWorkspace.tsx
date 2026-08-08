import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ActionResult, ServiceIntelligence } from "../../api/types";
import { BackNav } from "../BackNav";
import { SentinelPanel } from "../SentinelPanel";
import { workspaceContext } from "../context";
import { useWorkspace } from "../../context/WorkspaceContext";
import { LoadingBlock } from "../ui";

/**
 * The Provider Workspace shell.
 *
 * One layout every provider adopts, so a service page only writes its own work
 * surface and gets identity, health, intelligence and the assistant for free.
 * Nothing in here is Microsoft-specific - `service` is a key the backend maps
 * to providers, so GitHub, Slack and Google pages can adopt it unchanged.
 *
 *   ┌───────────────────────────────────────────────────┐
 *   │ BackNav · ServiceHeader (identity, health, actions)│
 *   ├───────────────────────────┬───────────────────────┤
 *   │ WORK SURFACE (children)   │ IntelligenceRail      │
 *   │                           │ SentinelPanel         │
 *   └───────────────────────────┴───────────────────────┘
 */
export interface ProviderWorkspaceProps {
  service: string;
  title: string;
  icon: ReactNode;
  /** Breadcrumb parent, e.g. Microsoft 365 */
  parent: { label: string; to: string };
  /** Buttons that propose Action Registry actions - never direct API writes. */
  quickActions?: ReactNode;
  /** Assistant wiring; omitted services simply render no panel. */
  assistant?: { contextLabel: string; endpointBase: string; placeholder?: string };
  /** Bumping this refetches the intelligence rail (after a write completes). */
  refreshKey?: number;
  children: ReactNode;
}

export function ProviderWorkspace({
  service,
  title,
  icon,
  parent,
  quickActions,
  assistant,
  refreshKey = 0,
  children,
}: ProviderWorkspaceProps) {
  const { active } = useWorkspace();
  const [intel, setIntel] = useState<ServiceIntelligence | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<ServiceIntelligence>(`/workspace/${service}/intelligence`)
      .then(setIntel)
      .catch(() => setIntel(null))
      .finally(() => setLoading(false));
  }, [service]);

  useEffect(load, [load, refreshKey]);

  return (
    <div className="flex flex-col gap-6 xl:flex-row">
      <div className="min-w-0 flex-1">
        <BackNav
          back={{ to: parent.to, label: parent.label }}
          crumbs={[{ label: "Dashboard", to: "/" }, { label: parent.label, to: parent.to }, { label: title }]}
        />
        <ServiceHeader title={title} icon={icon} intel={intel} loading={loading} quickActions={quickActions} />
        <div className="mt-5">{children}</div>
      </div>

      <aside className="w-full flex-none xl:w-[360px]">
        <div className="flex flex-col gap-4 xl:sticky xl:top-6">
          <IntelligenceRail intel={intel} loading={loading} />
          {assistant && (
            <div className="card overflow-hidden p-0 sm:p-0" style={{ minHeight: 380 }}>
              <SentinelPanel
                contextLabel={assistant.contextLabel}
                identity={workspaceContext(active)}
                endpointBase={assistant.endpointBase}
                placeholder={assistant.placeholder}
              />
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

/** Identity, health and the service's quick actions - one row, always the same
 *  shape, so a user reads any provider page the same way. */
function ServiceHeader({
  title,
  icon,
  intel,
  loading,
  quickActions,
}: {
  title: string;
  icon: ReactNode;
  intel: ServiceIntelligence | null;
  loading: boolean;
  quickActions?: ReactNode;
}) {
  const health = intel?.health;
  const tone =
    health === "error" || health === "token_revoked"
      ? "text-crit"
      : health === "ready" || health === "live"
        ? "text-good"
        : "text-ink-faint";
  const label =
    !intel?.connected
      ? "Not connected"
      : health === "token_revoked"
        ? "Reconnect needed"
        : health === "error"
          ? "Sync failing"
          : "Connected";

  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-md bg-surface-2">{icon}</div>
        <div>
          <h1 className="text-h2 font-medium leading-tight text-balance">{title}</h1>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-caption text-ink-faint">
            <span className={`font-semibold ${tone}`}>{loading ? "…" : label}</span>
            {intel?.account && <span>· {intel.account}</span>}
            {intel?.last_synced_at && (
              <span>
                · synced{" "}
                {new Date(intel.last_synced_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
              </span>
            )}
          </div>
        </div>
      </div>
      {quickActions && <div className="flex flex-wrap items-center gap-2">{quickActions}</div>}
    </div>
  );
}

/** Findings, situations and recommendations for THIS service.
 *  Provider-agnostic: it renders whatever the generic endpoint returns. */
function IntelligenceRail({ intel, loading }: { intel: ServiceIntelligence | null; loading: boolean }) {
  if (loading && !intel) return <LoadingBlock />;
  if (!intel) return null;

  const quiet = intel.findings.length === 0 && intel.situations.length === 0;

  return (
    <div className="card">
      <div className="mb-3 flex items-center gap-2">
        <span className="relative h-[13px] w-[13px] flex-none rounded-full border border-ink" aria-hidden="true">
          <span className="absolute inset-[4px] rounded-full bg-brand" />
        </span>
        <span className="text-small font-semibold text-ink">What Sentinel sees here</span>
      </div>

      {quiet ? (
        <p className="text-caption leading-relaxed text-ink-faint">
          Nothing needs your attention in this service right now.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {intel.situations.length > 0 && (
            <section>
              <div className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-ink-faint">
                Situations
              </div>
              <ul className="flex flex-col gap-2">
                {intel.situations.map((s) => (
                  <li key={s.id} className="rounded-md border border-border px-3 py-2">
                    <div className="text-small font-medium text-ink">{s.title}</div>
                    {s.explanation && (
                      <p className="mt-1 text-caption leading-relaxed text-ink-dim">{s.explanation}</p>
                    )}
                    {s.recommendations.length > 0 && (
                      <ul className="mt-1.5 flex flex-col gap-1">
                        {s.recommendations.map((r, i) => (
                          <li key={i} className="text-caption text-ink-faint">
                            → {r.action}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {intel.findings.length > 0 && (
            <section>
              <div className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-ink-faint">
                Findings
              </div>
              <ul className="flex flex-col gap-2">
                {intel.findings.slice(0, 8).map((f) => (
                  <li key={f.id} className="flex items-start gap-2">
                    <span
                      className={`mt-1.5 h-1.5 w-1.5 flex-none rounded-full ${
                        f.tier === "critical" ? "bg-crit" : f.tier === "review" ? "bg-warn" : "bg-ink-faint"
                      }`}
                      aria-hidden="true"
                    />
                    <div className="min-w-0">
                      <div className="truncate text-small text-ink">{f.title}</div>
                      <div className="truncate text-caption text-ink-faint">{f.why}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * A button that proposes an Action Registry action and, when the registry says
 * a confirmation is required, shows the server's own preview before executing.
 *
 * This component is the ONLY way a workspace page changes anything. It never
 * calls a provider API - it proposes, the user confirms, the server executes,
 * verifies and audits. Undo is offered when the action is compensatable.
 */
export function ActionButton({
  actionType,
  params,
  label,
  confirmLabel = "Confirm",
  undoable = false,
  onDone,
  variant = "ghost",
  disabled,
}: {
  actionType: string;
  params: Record<string, unknown>;
  label: string;
  confirmLabel?: string;
  /** Whether this action's ActionSpec declares a compensation. Passed
   *  explicitly rather than guessed, so Undo never appears when it cannot
   *  work - the same rule the backend registry follows. */
  undoable?: boolean;
  onDone?: () => void;
  variant?: "primary" | "ghost";
  disabled?: boolean;
}) {
  const [pending, setPending] = useState<null | { id: string; preview: Record<string, unknown> }>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<null | { id: string }>(null);
  const [error, setError] = useState<string | null>(null);

  async function propose() {
    setBusy(true);
    setError(null);
    try {
      const action = await api.post<ActionResult>("/actions", {
        action_type: actionType,
        params,
        source_kind: "workspace",
      });
      // The registry decides whether a confirmation is required. Anything
      // external - every Microsoft write - comes back awaiting_approval.
      if (action.status === "approved") {
        await run(action.id, false);
      } else {
        setPending({ id: action.id, preview: action.preview || {} });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start that");
    } finally {
      setBusy(false);
    }
  }

  async function run(id: string, needsApproval: boolean) {
    setBusy(true);
    setError(null);
    try {
      if (needsApproval) await api.post(`/actions/${id}/approve`);
      const result = await api.post<ActionResult>(`/actions/${id}/execute`);
      if (result.status === "failed") {
        setError(result.error || "The provider refused that");
        setPending(null);
        return;
      }
      setPending(null);
      // `unknown` means executed but unconfirmed - say so rather than claiming
      // success, because the change may well exist.
      if (result.status === "unknown") setError("Applied, but Sentinel couldn't confirm it");
      setDone({ id });
      onDone?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't go through");
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    if (!done) return;
    setBusy(true);
    try {
      await api.post(`/actions/${done.id}/undo`);
      setDone(null);
      onDone?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't undo that");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <span className="inline-flex items-center gap-2 text-caption text-ink-faint">
        <span className="text-good">Done</span>
        {undoable && (
          <button onClick={undo} disabled={busy} className="underline underline-offset-2 hover:text-ink">
            Undo
          </button>
        )}
        {error && <span className="text-warn">{error}</span>}
      </span>
    );
  }

  if (pending && pending.preview.irreversible) {
    const p = pending.preview;
    return (
      <div className="w-full rounded-md border border-crit/50 bg-crit/5 p-3">
        <div className="flex items-center gap-2">
          <span className="text-caption font-semibold uppercase tracking-wide text-crit">
            High risk · cannot be undone
          </span>
        </div>
        <p className="mt-1 text-caption text-ink-dim">{p.warning as string}</p>
        <dl className="mt-2.5 flex flex-col gap-1.5 rounded-md border border-border bg-surface px-3 py-2.5">
          <div className="flex gap-2">
            <dt className="w-16 flex-none text-caption text-ink-faint">To</dt>
            <dd className="min-w-0 flex-1 break-words text-caption text-ink">{(p.to as string[])?.join(", ")}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-16 flex-none text-caption text-ink-faint">Subject</dt>
            <dd className="min-w-0 flex-1 break-words text-caption font-medium text-ink">{p.subject as string}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-16 flex-none text-caption text-ink-faint">Message</dt>
            <dd className="min-w-0 flex-1 whitespace-pre-wrap break-words text-caption text-ink-dim">
              {p.message as string}
            </dd>
          </div>
        </dl>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            onClick={() => run(pending.id, true)}
            disabled={busy}
            className="rounded-md bg-crit px-3 py-1.5 text-caption font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Sending…" : "Send now"}
          </button>
          <button
            onClick={() => setPending(null)}
            disabled={busy}
            className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
          >
            Cancel
          </button>
          {error && <span className="text-caption text-crit">{error}</span>}
        </div>
      </div>
    );
  }

  if (pending) {
    const summary = (pending.preview.summary as string) || label;
    return (
      <span className="inline-flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface/60 px-2.5 py-1.5">
        <span className="text-caption text-ink-dim">{summary}</span>
        <button onClick={() => run(pending.id, true)} disabled={busy} className="btn-primary px-2.5 py-1 text-caption">
          {busy ? "Working…" : confirmLabel}
        </button>
        <button
          onClick={() => setPending(null)}
          disabled={busy}
          className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
        >
          Cancel
        </button>
        {error && <span className="text-caption text-crit">{error}</span>}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button
        onClick={propose}
        disabled={busy || disabled}
        className={
          variant === "primary"
            ? "btn-primary"
            : "rounded-md border border-border px-2.5 py-1.5 text-caption text-ink-dim transition-colors hover:border-border-strong hover:text-ink disabled:opacity-50"
        }
      >
        {busy ? "…" : label}
      </button>
      {error && <span className="text-caption text-crit">{error}</span>}
    </span>
  );
}
