import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { Connection } from "../api/types";
import { AttentionStrip, CatchMeUpCard } from "../components/AttentionStrip";
import { ChannelCards } from "../components/ChannelCards";
import { GroupCards } from "../components/GroupCards";
import { IntegrationCardGrid } from "../components/IntegrationCardGrid";
import { useWorkspace } from "../context/WorkspaceContext";

const GOOGLE_ERROR_MESSAGES: Record<string, string> = {
  session_expired: "That connect link expired — try again.",
  no_refresh_token: "Google didn't grant offline access — try disconnecting in your Google Account settings and reconnecting.",
};

/** The dashboard. "Today's Brief" used to render here too, but the
 * Attention strip made it redundant (the same agent findings surface as
 * attention items, with lifecycle actions the brief never had) - briefs
 * remain browsable under History, and agents keep running on schedule. */
export function BriefPage() {
  const { workspaces, active, setActiveId } = useWorkspace();
  const [searchParams, setSearchParams] = useSearchParams();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Re-fetch whenever the active workspace changes (Group/Channel cards
    // switch it) - previously this only ran once on mount, so switching
    // workspaces via the sidebar left this page showing stale data.
    if (!active) return;
    setLoading(true);
    api
      .get<Connection[]>("/connections")
      .then(setConnections)
      .catch(() => setConnections([]))
      .finally(() => setLoading(false));
  }, [active?.id]);

  const connectedBanner = searchParams.get("connected");
  const googleError = searchParams.get("google_error");

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

      {active?.is_demo && (
        <div className="mb-5 rounded-md border border-watch/40 bg-watch/5 px-4 py-3 text-[12.5px] text-watch">
          <b>Sample workspace.</b> Everything here is realistic demo data — no real account is connected, and nothing
          you do here touches your own mail, calendar or files. Sentinel's detection and AI are genuinely running
          against it.
        </div>
      )}

      {/* The attention loop leads the dashboard (Phase 2q): what changed
          while you were away, then what needs you now - everything else
          comes after. Keyed by workspace so switching re-fetches. */}
      <CatchMeUpCard key={`catchup-${active?.id}`} />
      <AttentionStrip key={`attention-${active?.id}`} />

      <GroupCards workspaces={workspaces} activeId={active?.id ?? null} onSelect={setActiveId} />
      <ChannelCards onSelectWorkspace={setActiveId} />

      <div className="mb-2.5 font-mono text-[13px] font-bold uppercase tracking-wide text-ink-dim">My Connections</div>
      <IntegrationCardGrid connections={connections} />
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
      <button onClick={onDismiss} aria-label="Dismiss" className="flex-none opacity-70 hover:opacity-100">
        ✕
      </button>
    </div>
  );
}
