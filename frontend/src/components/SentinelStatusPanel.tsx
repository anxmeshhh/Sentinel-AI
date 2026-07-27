import type { ReactNode } from "react";

import type { SentinelStatus } from "../api/types";

/** "11:08 PM" - the only time format that reads at a glance on the status card. */
function clockTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className={`text-body font-semibold tabular-nums ${tone ?? "text-ink"}`}>{value}</span>
      <span className="text-micro uppercase tracking-wide text-ink-faint">{label}</span>
    </div>
  );
}

/**
 * SECTION 1 - the first thing the page shows: is Sentinel working?
 *
 * A single glanceable answer (the dot) over the counts that prove it checked
 * everything, with provider errors surfaced right here because a broken sense
 * is the one thing that must never be buried under findings.
 */
export function SentinelStatusCard({
  status,
  onSync,
  syncing,
}: {
  status: SentinelStatus | null;
  onSync: () => void;
  syncing: boolean;
}) {
  const healthy = status?.healthy ?? true;
  return (
    <section className="card mb-4 p-4">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span
            aria-hidden
            className={`inline-block h-2.5 w-2.5 rounded-full ${healthy ? "bg-good" : "bg-crit"}`}
          />
          <h2 className="text-body font-medium text-ink">Sentinel Status</h2>
          {!healthy && <span className="text-caption text-crit">Attention needed</span>}
        </div>
        <button
          onClick={onSync}
          disabled={syncing}
          className="rounded-md border border-border px-3 py-1.5 text-caption text-ink-dim transition-colors hover:border-border-strong hover:text-ink disabled:opacity-50"
        >
          {syncing ? "Syncing…" : "Sync Now"}
        </button>
      </div>

      <div className="flex flex-wrap gap-x-8 gap-y-4">
        <Stat label="Monitoring" value={`${status?.provider_count ?? 0} providers`} />
        <Stat label="Resources" value={status?.resource_count ?? 0} />
        <Stat label="Last sync" value={clockTime(status?.last_synced_at ?? null)} />
        <Stat label="Signals analysed" value={(status?.signals_analysed ?? 0).toLocaleString()} />
        <Stat
          label="Findings"
          value={status?.findings_count ?? 0}
          tone={status && status.findings_count > 0 ? "text-warn" : "text-ink"}
        />
      </div>

      {status && status.errors.length > 0 && (
        <div className="mt-4 flex flex-col gap-1.5 border-t border-border pt-3">
          {status.errors.map((e) => (
            <div key={e} className="flex items-center gap-2 text-caption text-crit">
              <span aria-hidden>⚠</span>
              <span>{e}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/**
 * SECTION 2 - the instant summary before any individual finding. One row that
 * answers "how much, and how serious" before the eye reaches the list.
 */
export function TodaysAttention({
  critical,
  needsReview,
  reminders,
  dismissed,
}: {
  critical: number;
  needsReview: number;
  reminders: number;
  dismissed: number;
}) {
  const rows = [
    { label: "Critical", value: critical, dot: "bg-crit", tone: critical > 0 ? "text-ink" : "text-ink-faint" },
    { label: "Needs review", value: needsReview, dot: "bg-warn", tone: needsReview > 0 ? "text-ink" : "text-ink-faint" },
    { label: "Reminders", value: reminders, dot: "bg-watch", tone: reminders > 0 ? "text-ink" : "text-ink-faint" },
    { label: "Dismissed", value: dismissed, dot: "bg-ink-faint", tone: "text-ink-faint" },
  ];
  return (
    <section className="mb-4">
      <h3 className="mb-2.5 text-micro uppercase tracking-wide text-ink-faint">Today's attention</h3>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center gap-2">
            <span aria-hidden className={`inline-block h-1.5 w-1.5 rounded-full ${r.dot}`} />
            <span className="text-small text-ink-dim">{r.label}</span>
            <span className={`text-small font-semibold tabular-nums ${r.tone}`}>{r.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

/**
 * SECTION 4 - "did Sentinel check everything?" Naming each provider it
 * actually analysed does what "checked 204 items" cannot: it earns trust by
 * showing the work, not just asserting it.
 */
export function ProvidersChecked({ status }: { status: SentinelStatus | null }) {
  if (!status || status.providers.length === 0) return null;
  return (
    <section className="mb-4">
      <h3 className="mb-2.5 text-micro uppercase tracking-wide text-ink-faint">Providers checked</h3>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        {status.providers.map((p) => (
          <span key={p.provider} className="flex items-center gap-1.5 text-small">
            <span aria-hidden className={p.ok ? "text-good" : "text-crit"}>{p.ok ? "✓" : "⚠"}</span>
            <span className={p.ok ? "text-ink-dim" : "text-crit"}>{p.label}</span>
            {p.live ? (
              <span className="text-micro text-ink-faint">live</span>
            ) : (
              p.signal_count > 0 && <span className="text-micro tabular-nums text-ink-faint">{p.signal_count}</span>
            )}
          </span>
        ))}
      </div>
      <p className="mt-2.5 text-caption text-ink-faint">
        {status.signals_analysed.toLocaleString()} signals analysed across {status.provider_count} providers
      </p>
    </section>
  );
}

/**
 * SECTION 3 (empty) - a clear all-clear that reassures by showing what was
 * checked, not a blank space that reads as broken. Only shown when the sync
 * has genuinely run and nothing qualifies.
 */
export function FindingsEmptyState({ status }: { status: SentinelStatus | null }) {
  const labels = status?.providers.map((p) => p.label) ?? [];
  const providerPhrase =
    labels.length === 0
      ? "your connected tools"
      : labels.length === 1
        ? labels[0]
        : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
  const signals = status?.signals_analysed ?? 0;
  return (
    <div className="rounded-md border border-border bg-surface-2/40 px-5 py-8 text-center">
      <div className="mb-2 text-h3" aria-hidden>🎉</div>
      <p className="text-body font-medium text-ink">Nothing needs your attention.</p>
      <p className="mx-auto mt-1.5 max-w-md text-small text-ink-dim">
        Sentinel analysed {signals.toLocaleString()} signal{signals === 1 ? "" : "s"} across {providerPhrase}.
        No operational risks were detected.
      </p>
    </div>
  );
}
