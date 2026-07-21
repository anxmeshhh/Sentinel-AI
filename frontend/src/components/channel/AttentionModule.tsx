import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import type { ChannelBriefing } from "../../api/types";
import { attentionIcon, EvidenceLink } from "../AttentionStrip";
import { PROVIDER_LABEL } from "../ChannelSetupChecklist";
import { Button, ButtonLink, EmptyState, Icon, LoadingBlock } from "../ui";

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

  if (loading) return <LoadingBlock />;
  if (!briefing) return <EmptyState title="Couldn't load attention" description="The request failed. Try refreshing." />;

  if (briefing.no_connections) {
    return (
      <EmptyState
        title="No connections assigned"
        description="This channel has no authorized connections yet, so there is nothing to watch. An admin assigns them in Extensions."
      />
    );
  }

  if (briefing.items.length === 0) {
    // Two very different facts, and only one of them is the reader's to fix.
    const blocked = briefing.blocking_providers.length > 0;
    return (
      <EmptyState
        title={blocked ? "Empty for you — setup incomplete" : "Nothing needs attention"}
        description={
          blocked
            ? `You haven't connected ${briefing.blocking_providers
                .map((p) => PROVIDER_LABEL[p] ?? p)
                .join(", ")} yet, so this is empty for you — not because nothing is happening here.`
            : "Nothing in this channel's authorized connections needs a decision right now."
        }
        action={blocked ? <ButtonLink to={`/channels/${teamId}/extensions`} size="sm">Finish setup</ButtonLink> : undefined}
      />
    );
  }

  return (
    <div className="rounded-md border border-brand/25 bg-brand/[0.05] p-4 shadow-card">
      <div className="mb-2 flex items-center justify-between">
        <span className="label-sub font-bold text-brand">
          {briefing.items.length} item{briefing.items.length === 1 ? "" : "s"}
        </span>
        <Button size="sm" variant="ghost" onClick={load}>
          <Icon name="refresh" size={14} />
          Refresh
        </Button>
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
