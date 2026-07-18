import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { Brief, Connection } from "../api/types";
import { ChannelCards } from "../components/ChannelCards";
import { FindingCard } from "../components/FindingCard";
import { GroupCards } from "../components/GroupCards";
import { IntegrationCardGrid } from "../components/IntegrationCardGrid";
import { useWorkspace } from "../context/WorkspaceContext";

const GOOGLE_ERROR_MESSAGES: Record<string, string> = {
  session_expired: "That connect link expired — try again.",
  no_refresh_token: "Google didn't grant offline access — try disconnecting in your Google Account settings and reconnecting.",
};

export function BriefPage() {
  const { workspaces, active, setActiveId } = useWorkspace();
  const [searchParams, setSearchParams] = useSearchParams();
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
    // Re-fetch whenever the active workspace changes (Group/Channel cards
    // switch it) - previously this only ran once on mount, so switching
    // workspaces via the sidebar left this page showing stale data.
    if (active) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id]);

  async function triggerRun() {
    const githubConnection = connections.find((c) => c.provider === "github");
    if (!githubConnection) return;
    setTriggering(true);
    try {
      await api.post("/runs", { connection_id: githubConnection.id });
    } finally {
      setTriggering(false);
    }
  }

  const connectedBanner = searchParams.get("connected");
  const googleError = searchParams.get("google_error");
  const githubConnection = connections.find((c) => c.provider === "github");

  if (loading) return <div className="text-ink-dim">Loading&hellip;</div>;

  return (
    <div>
      {connectedBanner === "google" && (
        <Banner tone="good" onDismiss={() => setSearchParams({})}>
          Google connected — Calendar and Gmail will start syncing on the next run.
        </Banner>
      )}
      {googleError && (
        <Banner tone="crit" onDismiss={() => setSearchParams({})}>
          {GOOGLE_ERROR_MESSAGES[googleError] ?? "Couldn't connect Google — try again."}
        </Banner>
      )}

      <GroupCards workspaces={workspaces} activeId={active?.id ?? null} onSelect={setActiveId} />
      <ChannelCards onSelectWorkspace={setActiveId} />

      <div className="mb-2.5 font-mono text-[13px] font-bold uppercase tracking-wide text-ink-dim">My Connections</div>
      <IntegrationCardGrid connections={connections} onChanged={load} />

      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="mb-1 text-xl font-semibold text-balance">Today's Brief</h1>
          <p className="font-mono text-[13px] text-ink-dim">
            {githubConnection ? `${githubConnection.org}/${githubConnection.repo}` : "no repository connected"}
            {brief && ` · generated ${new Date(brief.generated_at).toLocaleString()}`}
          </p>
        </div>
        <button
          onClick={triggerRun}
          disabled={triggering || !githubConnection}
          className="rounded-md border border-border bg-surface px-3 py-1.5 font-mono text-[11.5px] text-ink-dim hover:border-accent hover:text-ink disabled:opacity-50"
        >
          {triggering ? "QUEUED…" : "↻ RE-RUN NOW"}
        </button>
      </div>

      {error && <p className="mb-4 text-[13px] text-crit">{error}</p>}

      {!brief ? (
        <div className="max-w-lg rounded-md border border-dashed border-border p-10 text-center text-ink-dim">
          No brief generated yet. Connect a source above and trigger a run, or wait for the next scheduled poll.
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

function Banner({ tone, children, onDismiss }: { tone: "good" | "crit"; children: string; onDismiss: () => void }) {
  return (
    <div
      className={`mb-5 flex items-center justify-between gap-3 rounded-md border px-3.5 py-2.5 text-[12.5px] ${
        tone === "good" ? "border-good/40 bg-good/10 text-good" : "border-crit/40 bg-crit/10 text-crit"
      }`}
    >
      <span>{children}</span>
      <button onClick={onDismiss} className="flex-none opacity-70 hover:opacity-100">
        ✕
      </button>
    </div>
  );
}
