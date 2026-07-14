import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { Brief, Connection } from "../api/types";
import { FindingCard } from "../components/FindingCard";

export function BriefPage() {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const conns = await api.get<Connection[]>("/connections");
      setConnections(conns);
      const latest = await api.get<Brief>("/briefs/latest");
      setBrief(latest);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setBrief(null);
      } else {
        setError(e instanceof Error ? e.message : "Failed to load brief");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function triggerRun() {
    if (connections.length === 0) return;
    setTriggering(true);
    try {
      await api.post("/runs", { connection_id: connections[0].id });
    } finally {
      setTriggering(false);
    }
  }

  if (loading) return <div className="text-ink-dim">Loading&hellip;</div>;

  if (connections.length === 0) {
    return (
      <div className="max-w-lg rounded-md border border-dashed border-border p-10 text-center text-ink-dim">
        <p className="mb-3 text-[14px]">No repository connected yet.</p>
        <Link to="/settings" className="font-mono text-[13px] font-semibold text-accent-text hover:underline">
          Connect a repository &rarr;
        </Link>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="mb-1 text-xl font-semibold text-balance">Today's Brief</h1>
          <p className="font-mono text-[13px] text-ink-dim">
            {connections[0].org}/{connections[0].repo}
            {brief && ` · generated ${new Date(brief.generated_at).toLocaleString()}`}
          </p>
        </div>
        <button
          onClick={triggerRun}
          disabled={triggering}
          className="rounded-md border border-border bg-surface px-3 py-1.5 font-mono text-[11.5px] text-ink-dim hover:border-accent hover:text-ink disabled:opacity-50"
        >
          {triggering ? "QUEUED…" : "↻ RE-RUN NOW"}
        </button>
      </div>

      {error && <p className="mb-4 text-[13px] text-crit">{error}</p>}

      {!brief ? (
        <div className="max-w-lg rounded-md border border-dashed border-border p-10 text-center text-ink-dim">
          No brief generated yet. Trigger a run above, or wait for the next scheduled poll.
        </div>
      ) : (
        <>
          <div className="mb-6 rounded-r-md border-l-[3px] border-accent bg-surface p-4">
            <b className="text-accent-text">{brief.narrative}</b>
          </div>

          {Object.entries(brief.data_freshness).map(([agent, note]) => (
            <p key={agent} className="mb-3 font-mono text-[12px] text-warn">
              ⚠ {agent}: {note}
            </p>
          ))}

          <div className="flex flex-col gap-3">
            {brief.findings.length === 0 ? (
              <p className="text-ink-dim">No findings above the confidence threshold today.</p>
            ) : (
              brief.findings.map((f) => <FindingCard key={f.id} finding={f} />)
            )}
          </div>
        </>
      )}
    </div>
  );
}
