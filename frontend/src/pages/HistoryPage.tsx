import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { BriefSummary } from "../api/types";
import { BackNav } from "../components/BackNav";

export function HistoryPage() {
  const [briefs, setBriefs] = useState<BriefSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<BriefSummary[]>("/briefs")
      .then(setBriefs)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load history"));
  }, []);

  return (
    <div>
      <BackNav back={{ to: "/", label: "Dashboard" }} />
      <h1 className="mb-1 text-xl font-semibold text-balance">Brief History</h1>
      <p className="mb-5 text-[13px] text-ink-dim">
        Every brief Sentinel has generated for this repository.
      </p>

      {error && <p className="text-crit">{error}</p>}

      {briefs.length === 0 ? (
        <div className="max-w-lg rounded-md border border-dashed border-border p-10 text-center text-ink-dim">
          No briefs generated yet.
        </div>
      ) : (
        <div className="rounded-md border border-border bg-surface">
          {briefs.map((b) => (
            <div key={b.id} className="grid grid-cols-[92px_1fr] gap-3.5 border-b border-border p-3.5 last:border-b-0">
              <div className="font-mono text-[12px] text-ink-faint">
                {new Date(b.generated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
              </div>
              <div className="text-[13px]">{b.narrative}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
