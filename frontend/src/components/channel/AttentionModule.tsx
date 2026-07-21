import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { ChannelBriefing } from "../../api/types";
import { attentionIcon, EvidenceLink } from "../AttentionStrip";
import { PROVIDER_LABEL } from "../ChannelSetupChecklist";

/** What needs this channel's attention, scoped to its authorized connections. */
export function AttentionModule({ teamId }: { teamId: string }) {
  const [briefing, setBriefing] = useState<ChannelBriefing | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setBriefing(await api.get<ChannelBriefing>(`/teams/${teamId}/briefing`));
    } catch {
      setBriefing(null);
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <div className="text-body text-ink-dim">Loading&hellip;</div>;
  if (!briefing) return <div className="text-body text-crit">Couldn't load this channel's attention.</div>;

  if (briefing.no_connections) {
    return (
      <div className="rounded-md border border-dashed border-border-strong p-8 text-center text-small text-ink-faint">
        No connections are assigned to this channel yet, so there's nothing to watch. Assign one in Extensions.
      </div>
    );
  }

  if (briefing.items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border-strong p-8 text-center text-small text-ink-dim">
        {briefing.blocking_providers.length > 0 ? (
          <>
            Empty <em>for you</em> because you haven't connected{" "}
            {briefing.blocking_providers.map((p) => PROVIDER_LABEL[p] ?? p).join(", ")} — not because nothing is
            happening here.
          </>
        ) : (
          "Nothing needs this channel's attention right now."
        )}
      </div>
    );
  }

  return (
    <div className="rounded-md border border-accent/25 bg-accent/[0.04] p-4 shadow-card">
      <div className="mb-2 flex items-center justify-between">
        <span className="label-sub font-bold text-accent-text">
          {briefing.items.length} item{briefing.items.length === 1 ? "" : "s"}
        </span>
        <button onClick={load} className="text-caption text-ink-faint underline hover:text-ink">
          Refresh
        </button>
      </div>
      {briefing.narrative && <p className="mb-3 text-small leading-relaxed text-ink-dim">{briefing.narrative}</p>}
      <div className="flex flex-col gap-1.5">
        {briefing.items.map((item) => (
          <div key={item.id} className="flex items-start gap-2.5 text-small">
            <span className="mt-px flex-none">{attentionIcon(item)}</span>
            <div className="min-w-0 flex-1">
              <div className="truncate font-semibold text-ink">{item.title}</div>
              <div className="truncate text-caption text-ink-faint">{item.why}</div>
            </div>
            <EvidenceLink item={item} className="flex-none text-micro font-semibold text-accent-text hover:underline" />
          </div>
        ))}
      </div>
      <p className="mt-3 text-caption text-ink-faint">
        Scoped to this channel's authorized connections
        {briefing.connection_labels.length > 0 && `: ${briefing.connection_labels.join(", ")}`}. Mark items done in your
        personal{" "}
        <Link to="/attention" className="underline underline-offset-2 hover:text-ink">
          Attention
        </Link>{" "}
        hub.
      </p>
    </div>
  );
}
