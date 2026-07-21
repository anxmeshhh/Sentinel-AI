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
      <div className="section-head">
        <h1>Brief History</h1>
        <p>
          Every brief Sentinel has generated for this repository.
        </p>
      </div>

      {error && <p className="text-crit">{error}</p>}

      {briefs.length === 0 ? (
        <div className="max-w-lg rounded-md border border-dashed border-border-strong p-10 text-center text-ink-dim">
          No briefs generated yet.
        </div>
      ) : (
        <div className="card">
          {briefs.map((b) => (
            <div key={b.id} className="grid grid-cols-[92px_1fr] gap-3.5 border-b border-border p-3.5 last:border-b-0">
              <div className="text-small text-ink-faint">
                {new Date(b.generated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
              </div>
              <div className="text-body">{b.narrative}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
