import { useState } from "react";

import { api, ApiError } from "../api/client";
import type { Evidence, Investigation } from "../api/types";
import { Button } from "./ui";

const KIND_ICON: Record<string, string> = {
  email: "📧",
  calendar_event: "📅",
  pr: "🔀",
  commit: "⬆️",
  issue: "🐞",
  review_submitted: "👀",
  drive_file: "📄",
};

function confidenceCopy(value: number): { label: string; tone: string } {
  if (value >= 0.7) return { label: "well supported", tone: "text-good" };
  if (value >= 0.4) return { label: "partly supported", tone: "text-watch" };
  return { label: "thin evidence", tone: "text-crit" };
}

/**
 * The result of "Investigate This".
 *
 * The layout enforces the distinction the backend maintains: everything in
 * the upper half is the model's reading, everything under "Evidence" is a
 * row retrieved from the database with a link to the real thing. A user who
 * distrusts the narrative can check every fact it was built from, which is
 * the only reason a narrative like this is worth showing at all.
 */
export function InvestigationPanel({
  investigation,
  onRefresh,
  refreshing,
  onClose,
}: {
  investigation: Investigation;
  onRefresh: () => void;
  refreshing: boolean;
  onClose: () => void;
}) {
  const confidence = confidenceCopy(investigation.confidence);
  const grouped = investigation.evidence.reduce<Record<string, Evidence[]>>((acc, e) => {
    (acc[e.relation_label] ??= []).push(e);
    return acc;
  }, {});

  return (
    <div className="rounded-md border border-brand/25 bg-brand/[0.05] p-4 shadow-card">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="label-sub font-bold text-accent-text">Investigation ✨</div>
          <div className="truncate text-body font-semibold text-ink">{investigation.title}</div>
        </div>
        <div className="flex flex-none items-center gap-2">
          <Button size="sm" variant="secondary" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? "Re-investigating…" : "↻ Re-investigate"}
          </Button>
          <button onClick={onClose} aria-label="Close" className="text-lead text-ink-faint hover:text-ink">
            &times;
          </button>
        </div>
      </div>

      <Section label="What happened">
        <p className="text-small leading-relaxed text-ink-dim">{investigation.what_happened}</p>
      </Section>

      <Section label="Why it matters">
        <p className="text-small leading-relaxed text-ink-dim">{investigation.why_it_matters}</p>
      </Section>

      {investigation.contributing_factors.length > 0 && (
        <Section label="Likely contributing factors">
          <ul className="flex flex-col gap-1">
            {investigation.contributing_factors.map((factor) => (
              <li key={factor} className="text-small leading-relaxed text-ink-dim">
                • {factor}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {investigation.next_steps.length > 0 && (
        <Section label="Recommended next steps">
          <ul className="flex flex-col gap-1">
            {investigation.next_steps.map((step) => (
              <li key={step} className="text-small leading-relaxed text-ink-dim">
                → {step}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* The line between inference and fact, stated rather than implied. */}
      <div className="mb-2 mt-3 flex items-center gap-2 border-t border-border pt-3">
        <span className="label-sub">Evidence</span>
        <span className="text-micro text-ink-faint">
          {investigation.evidence.length} item{investigation.evidence.length === 1 ? "" : "s"} Sentinel actually found
        </span>
      </div>

      {investigation.evidence.length === 0 ? (
        <p className="text-caption leading-relaxed text-ink-faint">
          Nothing related was found in the data this context is authorized to read, so there was nothing to correlate.
        </p>
      ) : (
        <div className="flex flex-col gap-2.5">
          {Object.entries(grouped).map(([relation, items]) => (
            <div key={relation}>
              <div className="mb-1 text-micro uppercase tracking-wide text-ink-faint">{relation}</div>
              <div className="flex flex-col gap-1">
                {items.map((e) => (
                  <EvidenceRow key={e.signal_id} evidence={e} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mt-3 border-t border-border pt-2 text-micro text-ink-faint">
        Reading of the evidence is AI-generated —{" "}
        <span className={confidence.tone}>{confidence.label}</span> ({Math.round(investigation.confidence * 100)}%). The
        evidence itself is retrieved from your connected data, not generated.
      </div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="label-sub mb-1">{label}</div>
      {children}
    </div>
  );
}

function EvidenceRow({ evidence }: { evidence: Evidence }) {
  const when = evidence.occurred_at ? new Date(evidence.occurred_at).toLocaleDateString() : null;
  const body = (
    <>
      <span className="flex-none">{KIND_ICON[evidence.kind] ?? "•"}</span>
      <span className="min-w-0 flex-1 truncate">{evidence.title}</span>
      {when && <span className="flex-none text-micro text-ink-faint">{when}</span>}
    </>
  );

  return evidence.url ? (
    <a
      href={evidence.url}
      target="_blank"
      rel="noreferrer"
      className="flex items-center gap-2 rounded-md px-1.5 py-1 text-caption text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
    >
      {body}
    </a>
  ) : (
    <div className="flex items-center gap-2 px-1.5 py-1 text-caption text-ink-dim">{body}</div>
  );
}

/** Fetch/refresh state, so the Attention hub and any channel entry point
 *  share one implementation (same shape as useMeetingBrief). */
export function useInvestigation() {
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(path: string, { refresh = false } = {}) {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      setInvestigation(await api.post<Investigation>(`${path}${refresh ? "?refresh=true" : ""}`));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't investigate this item.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  return { investigation, loading, refreshing, error, load, clear: () => setInvestigation(null) };
}
