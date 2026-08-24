import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { ActionResult, ServiceIntelligence } from "../../api/types";
import { useWorkspace } from "../../context/WorkspaceContext";
import { BackNav } from "../BackNav";
import { workspaceContext } from "../context";
import { RecentActivity } from "../RecentActivity";
import { SentinelPanel, type SuggestionGroup } from "../SentinelPanel";
import { ServiceCard } from "../ServiceCard";
import { SyncButton } from "../SyncButton";
import { Action, ActionGroup, Badge, Button, LoadingBlock, TabBar, type TabBarItem } from "../ui";

/**
 * The Provider Workspace shell.
 *
 * One layout every leaf service page adopts, so a service page only writes
 * its own work surface and gets identity, health, intelligence, activity and
 * (where a real one exists) an AI panel for free.
 *
 *   ┌──────────────────────────────────────────────────────────┐
 *   │ BackNav · Header (identity, health, Sync Now, actions)     │
 *   │ Overview · Services · Insights · Activity · Settings       │
 *   ├──────────────────────────────────────────────────────────┤
 *   │ Overview: work surface (children) · insights · AI · activity│
 *   └──────────────────────────────────────────────────────────┘
 *
 * The floating Assistant button (mounted once, globally) is still the one
 * general way to ask Sentinel anything on this page. The AI panel here is a
 * different thing: it exists only where a real, already-built, provider-
 * SCOPED backend endpoint exists (SentinelPanel + /connections/{provider}
 * /command/stream - Google, GitHub, Microsoft today), because "the Gmail
 * assistant understands emails specifically" is a genuine capability those
 * endpoints have and the general Assistant does not. A provider with no such
 * endpoint (Zoom, Slack) gets no AI panel here rather than a relabelled
 * general assistant pretending to be scoped.
 */
export interface ProviderWorkspaceProps {
  service: string;
  title: string;
  icon: ReactNode;
  /** Breadcrumb parent, e.g. Microsoft 365 */
  parent: { label: string; to: string };
  /** Buttons that propose Action Registry actions - never direct API writes. */
  quickActions?: ReactNode;
  /** Bumping this refetches the intelligence rail (after a write completes). */
  refreshKey?: number;
  children: ReactNode;
  /** Only set for a provider with a real scoped chat endpoint. */
  assistant?: {
    endpointBase: string;
    contextLabel: string;
    placeholder?: string;
    suggestions?: string[];
    suggestionGroups?: SuggestionGroup[];
  };
  /** RecentActivity's `sources` filter - the ACTION_META labels that belong
   *  to this service (e.g. ["Gmail"]). Omitted, Activity shows nothing
   *  rather than every provider's history. */
  activitySources?: string[];
}

type TabKey = "overview" | "services" | "insights" | "activity" | "settings";

const TABS: TabBarItem<TabKey>[] = [
  { key: "overview", label: "Overview" },
  { key: "services", label: "Services" },
  { key: "insights", label: "Insights" },
  { key: "activity", label: "Activity" },
  { key: "settings", label: "Settings" },
];

export function ProviderWorkspace({
  service,
  title,
  icon,
  parent,
  quickActions,
  refreshKey = 0,
  children,
  assistant,
  activitySources,
}: ProviderWorkspaceProps) {
  const { active } = useWorkspace();
  const [intel, setIntel] = useState<ServiceIntelligence | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TabKey>("overview");

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<ServiceIntelligence>(`/workspace/${service}/intelligence`)
      .then(setIntel)
      .catch(() => setIntel(null))
      .finally(() => setLoading(false));
  }, [service]);

  useEffect(load, [load, refreshKey]);

  const insightCount = (intel?.findings.length ?? 0) + (intel?.situations.length ?? 0);

  return (
    <div>
      <BackNav
        back={{ to: parent.to, label: parent.label }}
        crumbs={[{ label: "Dashboard", to: "/" }, { label: parent.label, to: parent.to }, { label: title }]}
      />
      <ServiceHeader
        title={title}
        icon={icon}
        intel={intel}
        loading={loading}
        quickActions={
          <>
            {quickActions}
            <SyncButton service={service} onSynced={load} />
          </>
        }
      />

      <TabBar
        items={TABS.map((t) => (t.key === "insights" ? { ...t, count: insightCount } : t))}
        value={tab}
        onChange={setTab}
      />

      {tab === "overview" && (
        <div className="flex flex-col gap-6 xl:flex-row">
          <div className="min-w-0 flex-1">
            <div>{children}</div>

            <div className="mt-6 grid gap-4 lg:grid-cols-2">
              <IntelligenceCard title="Insights" intel={intel} loading={loading} limit={3} to={() => setTab("insights")} />
              <div className="flex flex-col gap-4">
                <RecentActivity scope="personal" limit={5} sources={activitySources} />
              </div>
            </div>
          </div>

          {assistant && (
            <aside className="w-full flex-none xl:w-[360px]">
              <div className="card h-[440px] overflow-hidden p-0 sm:p-0 xl:sticky xl:top-6">
                <SentinelPanel
                  contextLabel={assistant.contextLabel}
                  identity={workspaceContext(active)}
                  endpointBase={assistant.endpointBase}
                  placeholder={assistant.placeholder}
                  suggestions={assistant.suggestions}
                  suggestionGroups={assistant.suggestionGroups}
                />
              </div>
            </aside>
          )}
        </div>
      )}

      {tab === "services" && (
        <div className="max-w-sm">
          <ServiceCard
            icon={icon}
            name={title}
            status={!intel?.connected ? "Not connected" : "Connected"}
            desc={intel?.account ?? "This service on its own - see every connected service under one family."}
            connected={Boolean(intel?.connected)}
          />
          <Link to={parent.to} className="mt-3 inline-block text-caption text-accent-text hover:underline">
            View all {parent.label} services →
          </Link>
        </div>
      )}

      {tab === "insights" && <IntelligenceCard title="Insights" intel={intel} loading={loading} to={undefined} />}

      {tab === "activity" && (
        <RecentActivity scope="personal" limit={20} sources={activitySources} />
      )}

      {tab === "settings" && <SettingsTab title={title} parent={parent} intel={intel} loading={loading} />}
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
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-md bg-surface-2">{icon}</div>
        <div>
          <h1 className="text-h2 font-semibold tracking-tight text-ink">{title}</h1>
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
 *  Provider-agnostic: it renders whatever the generic endpoint returns.
 *  `limit` truncates for the Overview card; omitted, the Insights tab shows
 *  everything. */
function IntelligenceCard({
  title,
  intel,
  loading,
  limit,
  to,
}: {
  title: string;
  intel: ServiceIntelligence | null;
  loading: boolean;
  limit?: number;
  to?: () => void;
}) {
  if (loading && !intel) return <LoadingBlock />;
  if (!intel) return null;

  const findings = limit ? intel.findings.slice(0, limit) : intel.findings;
  const situations = limit ? intel.situations.slice(0, limit) : intel.situations;
  const quiet = intel.findings.length === 0 && intel.situations.length === 0;
  const more = limit && (intel.findings.length + intel.situations.length) > limit;

  return (
    <div className="card">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="relative h-[13px] w-[13px] flex-none rounded-full border border-ink" aria-hidden="true">
            <span className="absolute inset-[4px] rounded-full bg-brand" />
          </span>
          <span className="text-small font-semibold text-ink">{title}</span>
        </div>
        {more && to && (
          <button type="button" onClick={to} className="text-caption text-ink-faint hover:text-ink">
            View all →
          </button>
        )}
      </div>

      {quiet ? (
        <p className="text-caption leading-relaxed text-ink-faint">
          Nothing needs your attention in this service right now.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {situations.length > 0 && (
            <section>
              <div className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-ink-faint">
                Situations
              </div>
              <ul className="flex flex-col gap-2">
                {situations.map((s) => (
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

          {findings.length > 0 && (
            <section>
              <div className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-ink-faint">
                Findings
              </div>
              <ul className="flex flex-col gap-2">
                {findings.map((f) => (
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

/** Connection facts, read-only - the actual connect/reconnect/disconnect
 *  flow (OAuth, consent) lives once, on the family hub page, not
 *  re-implemented per leaf page. */
function SettingsTab({
  title,
  parent,
  intel,
  loading,
}: {
  title: string;
  parent: { label: string; to: string };
  intel: ServiceIntelligence | null;
  loading: boolean;
}) {
  if (loading) return <LoadingBlock />;
  return (
    <div className="card max-w-md">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="text-small font-semibold text-ink">Connection</span>
        <Badge tone={intel?.connected ? "good" : "neutral"}>{intel?.connected ? "Connected" : "Not connected"}</Badge>
      </div>
      <dl className="flex flex-col gap-2 text-caption">
        {intel?.account && (
          <div className="flex gap-2">
            <dt className="w-28 flex-none text-ink-faint">Account</dt>
            <dd className="text-ink-dim">{intel.account}</dd>
          </div>
        )}
        <div className="flex gap-2">
          <dt className="w-28 flex-none text-ink-faint">Last synced</dt>
          <dd className="text-ink-dim">{intel?.last_synced_at ? new Date(intel.last_synced_at).toLocaleString() : "Never"}</dd>
        </div>
      </dl>
      <p className="mt-4 text-caption text-ink-faint">
        Reconnecting or disconnecting {title} is managed from{" "}
        <Link to={parent.to} className="text-accent-text hover:underline">
          {parent.label}
        </Link>
        , alongside every other service in that family.
      </p>
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
      <ActionGroup>
        <Badge tone="good">Done</Badge>
        {undoable && <Action kind="undo" onClick={undo} disabled={busy} />}
        {error && <span className="text-caption text-warn">{error}</span>}
      </ActionGroup>
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
          {/* The one place a filled danger button is right: the preview above
              states exactly what goes out, and it cannot be undone. */}
          <Button
            size="sm"
            variant="danger"
            loading={busy}
            onClick={() => run(pending.id, true)}
            className="bg-crit/15"
          >
            Send now
          </Button>
          <Action kind="cancel" onClick={() => setPending(null)} disabled={busy} />
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
        <Action kind="confirm" label={confirmLabel} loading={busy} onClick={() => run(pending.id, true)} />
        <Action kind="cancel" onClick={() => setPending(null)} disabled={busy} />
        {error && <span className="text-caption text-crit">{error}</span>}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-2">
      <Button size="sm" variant={variant} loading={busy} disabled={disabled} onClick={propose}>
        {label}
      </Button>
      {error && <span className="text-caption text-crit">{error}</span>}
    </span>
  );
}
