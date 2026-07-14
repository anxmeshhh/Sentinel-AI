import { useNavigate } from "react-router-dom";

import type { Finding } from "../api/types";
import { severityBand } from "../api/types";
import { SeverityChip, severityStripeClass } from "./SeverityChip";

export function FindingCard({ finding }: { finding: Finding }) {
  const navigate = useNavigate();
  const severity = severityBand(finding.severity);
  const evidenceCount = countEvidence(finding.evidence);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => navigate(`/findings/${finding.id}`)}
      onKeyDown={(e) => e.key === "Enter" && navigate(`/findings/${finding.id}`)}
      className="grid cursor-pointer grid-cols-[4px_1fr] overflow-hidden rounded-md border border-border bg-surface shadow-sm transition-colors hover:border-accent"
    >
      <div className={severityStripeClass(severity)} />
      <div className="p-4">
        <div className="mb-1.5 flex flex-wrap items-center gap-2.5">
          <SeverityChip severity={severity} />
          <span className="text-[14.5px] font-semibold">{finding.summary}</span>
          <span className="tab-nums ml-auto font-mono text-[11.5px] text-ink-faint">
            {Math.round(finding.confidence * 100)}% confidence
          </span>
        </div>
        <p className="my-0.5 text-[13px] text-ink-dim">
          <b className="font-semibold text-ink">Root cause:</b> {finding.root_cause}
        </p>
        <p className="my-0.5 text-[13px] text-ink-dim">
          <b className="font-semibold text-ink">Suggested action:</b> {finding.suggested_action}
        </p>
        <div className="mt-2 flex gap-3.5 font-mono text-[11.5px] text-ink-faint">
          <span>{evidenceCount} item(s) cited</span>
          <span>View evidence &rarr;</span>
        </div>
      </div>
    </div>
  );
}

function countEvidence(evidence: Record<string, unknown>): number {
  return Object.values(evidence).reduce<number>((total, value) => {
    if (Array.isArray(value)) return total + value.length;
    return total + 1;
  }, 0);
}
