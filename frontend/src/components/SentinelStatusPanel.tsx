import { useState } from "react";

import type { SentinelStatus } from "../api/types";
import { Button } from "./ui";

/** "11:34 PM" - the only time format that reads at a glance on the header. */
function clockTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

/**
 * The verdict - Sentinel's executive summary, the first sentence read every
 * morning. It summarises the highest-priority state that exists ON THE PAGE,
 * across BOTH surfaces (attention items and situations), so it can never
 * contradict the findings below it. The strict hierarchy is:
 *
 *   1. Provider health   - if a sense failed, findings may be incomplete, so
 *                          nothing below can be fully trusted; say so first.
 *   2. Critical findings - something needs prompt action.
 *   3. Review findings   - operational risks worth a look (stalled repos,
 *                          at-risk services). This is where situations land.
 *   4. Reminders         - the user's own notes, nothing operational.
 *   5. All clear         - genuinely nothing, anywhere.
 *
 * The second line (`detail`) names what was found, so the summary is specific.
 */
function verdict(status: SentinelStatus | null): { dot: string; headline: string; detail: string | null } {
  if (!status) return { dot: "bg-ink-faint", headline: "Checking your systems…", detail: null };

  // 1 - provider health
  if (status.errors.length > 0) {
    return {
      dot: "bg-warn",
      headline: "Sentinel requires attention.",
      detail:
        status.errors.length === 1
          ? "A provider could not be analysed successfully. Some findings may be incomplete."
          : "One or more providers could not be analysed successfully. Some findings may be incomplete.",
    };
  }
  // 2 - critical
  if (status.critical_count > 0) {
    return {
      dot: "bg-crit",
      headline: "Immediate attention recommended.",
      detail: status.summary ?? "Sentinel detected critical operational issues requiring prompt action.",
    };
  }
  // 3 - review (where situations land)
  if (status.review_count > 0) {
    const n = status.review_count;
    return {
      dot: "bg-warn",
      headline: `${n} operational ${plural(n, "risk needs", "risks need")} your review.`,
      detail: status.summary ? `${status.summary} Review the findings below.` : "Review the findings below.",
    };
  }
  // 4 - reminders only
  if (status.reminder_count > 0) {
    const n = status.reminder_count;
    return {
      dot: "bg-watch",
      headline: `No operational risks — ${n} ${plural(n, "reminder", "reminders")} on your list.`,
      detail: "Nothing Sentinel flagged; these are your own notes.",
    };
  }
  // 5 - all clear
  return {
    dot: "bg-good",
    headline: `All clear. Sentinel checked ${status.resource_count} ${plural(status.resource_count, "resource", "resources")} across ${status.provider_count} providers.`,
    detail: "Nothing needs your attention.",
  };
}

/**
 * SECTION 1 - the briefing header. The verdict is the hero; the metrics are
 * demoted to a single muted line that proves the verdict rather than competing
 * with it. Provider errors surface here because a broken sense is part of "am
 * I healthy", and this is the one place it must never be missed.
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
  const v = verdict(status);
  // Last sync is deliberately NOT in this list - it belongs next to the Sync
  // button, as one piece of information, not lost among the other metrics.
  const metrics = status
    ? [
        `${status.signals_analysed.toLocaleString()} ${plural(status.signals_analysed, "signal", "signals")} analysed`,
        `${status.resource_count} ${plural(status.resource_count, "resource", "resources")}`,
        `${status.provider_count} providers`,
      ]
    : [];
  return (
    <section className="card mb-4 p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span aria-hidden className={`mt-1.5 inline-block h-3 w-3 flex-none rounded-full ${v.dot}`} />
          <div className="min-w-0">
            {/* SECTION 1: the verdict is the most important sentence on the page,
                so it is the largest and heaviest thing in the header. Its
                second line names what was found, so it is specific. */}
            <p className="text-h3 font-semibold leading-snug text-balance text-ink">{v.headline}</p>
            {v.detail && <p className="mt-1 text-small leading-snug text-ink-dim">{v.detail}</p>}
            {metrics.length > 0 && (
              <p className="mt-2 text-caption text-ink-faint">
                {metrics.map((m, i) => (
                  <span key={m}>
                    {i > 0 && <span className="px-1.5 text-ink-faint/50">·</span>}
                    {m}
                  </span>
                ))}
              </p>
            )}
          </div>
        </div>
        {/* Last sync + Sync Now, treated as one unit: the freshness and the
            control that refreshes it read together. */}
        <div className="flex flex-none items-center gap-3">
          <div className="text-right">
            <div className="text-micro uppercase tracking-wide text-ink-faint">Last sync</div>
            <div className="text-caption tabular-nums text-ink-dim">{clockTime(status?.last_synced_at ?? null)}</div>
          </div>
          <button
            onClick={onSync}
            disabled={syncing}
            className="rounded-md border border-border px-3 py-1.5 text-caption text-ink-dim transition-colors hover:border-border-strong hover:text-ink disabled:opacity-50"
          >
            {syncing ? "Checking…" : "Sync Now"}
          </button>
        </div>
      </div>

      {status && status.errors.length > 0 && (
        <div className="mt-4 flex flex-col gap-1.5 border-t border-border pt-3.5">
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
 * SECTION 2 - the instant overview before any one finding. One quiet row:
 * how much, and how serious.
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
    <section className="mb-5 flex flex-wrap items-center gap-x-6 gap-y-2">
      <h3 className="text-micro uppercase tracking-wide text-ink-faint">Today</h3>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2">
          <span aria-hidden className={`inline-block h-1.5 w-1.5 rounded-full ${r.dot}`} />
          <span className="text-small text-ink-dim">{r.label}</span>
          <span className={`text-small font-semibold tabular-nums ${r.tone}`}>{r.value}</span>
        </div>
      ))}
    </section>
  );
}

/** The ✓ provider pills, shared by the standalone section and the all-clear
 *  state so "what did Sentinel check" looks identical wherever it appears. */
function ProviderPills({ status }: { status: SentinelStatus }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2">
      {status.providers.map((p) => (
        <span key={p.provider} className="flex items-center gap-1.5 text-small">
          <span aria-hidden className={p.ok ? "text-good" : "text-crit"}>{p.ok ? "✓" : "⚠"}</span>
          <span className={p.ok ? "text-ink-dim" : "text-crit"}>{p.label}</span>
          {p.note ? (
            <span className="text-micro text-ink-faint">{p.note}</span>
          ) : p.live ? (
            <span className="text-micro text-ink-faint">live</span>
          ) : (
            p.signal_count > 0 && <span className="text-micro tabular-nums text-ink-faint">{p.signal_count}</span>
          )}
        </span>
      ))}
    </div>
  );
}

/**
 * SECTION 4 - "did Sentinel check everything?" Naming each provider it
 * verified does what "checked 224 items" cannot: it earns trust by showing
 * the work. Shown below findings when findings exist; folded into the
 * all-clear state otherwise, since that is where doubt would form.
 */
export function ProvidersChecked({ status }: { status: SentinelStatus | null }) {
  const [open, setOpen] = useState(false);
  if (!status || status.providers.length === 0) return null;

  // Summarised, not spelled out. Twelve ticked provider pills with counts is a
  // wall the eye slides off, and it sat directly beneath the findings it was
  // meant to reassure about. The one-line version answers the same doubt -
  // "did anything actually run?" - and the full list is still one click away
  // for the moment someone genuinely wants to audit it.
  return (
    <section className="border-t border-rule pt-4">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p className="text-caption text-ink-faint">
          Checked {status.providers.length} {status.providers.length === 1 ? "provider" : "providers"} ·{" "}
          {status.signals_analysed.toLocaleString()} signals · {status.findings_count}{" "}
          {status.findings_count === 1 ? "finding" : "findings"}
        </p>
        <Button size="sm" variant="ghost" onClick={() => setOpen((v) => !v)}>
          {open ? "Hide" : "Show"}
        </Button>
      </div>
      {open && (
        <div className="mt-3 [&>div]:justify-start">
          <ProviderPills status={status} />
        </div>
      )}
    </section>
  );
}

/**
 * SECTION 3 (empty) - the all-clear. It reassures by naming exactly what was
 * checked, so an empty findings list reads as a *result Sentinel produced*,
 * not a void. Providers are folded in here (Section 4) because this is the
 * moment a user would otherwise wonder whether anything ran at all.
 */
export function FindingsEmptyState({ status }: { status: SentinelStatus | null }) {
  const signals = status?.signals_analysed ?? 0;
  return (
    <div className="rounded-md border border-border bg-surface-2/40 px-6 py-14 text-center">
      <div className="mb-3 text-h2" aria-hidden>🎉</div>
      <p className="text-body font-medium text-ink">Nothing needs your attention.</p>
      <p className="mx-auto mt-2.5 max-w-md text-small leading-relaxed text-ink-dim">
        Sentinel analysed {signals.toLocaleString()} {signals === 1 ? "signal" : "signals"} across all connected
        providers. No operational risks were detected.
      </p>
      {status && status.providers.length > 0 && (
        <div className="mx-auto mt-8 max-w-lg border-t border-border pt-6">
          <ProviderPills status={status} />
          <p className="mt-3.5 text-caption text-ink-faint">
            {signals.toLocaleString()} signals analysed · {status.findings_count} findings generated
          </p>
        </div>
      )}
    </div>
  );
}
