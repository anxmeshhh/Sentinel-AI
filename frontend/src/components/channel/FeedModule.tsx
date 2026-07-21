import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ChannelFeed } from "../../api/types";
import { Button, EmptyState, Icon, LoadingBlock } from "../ui";

/** Normalized updates from the channel's authorized connections.
 *
 * Refetches on mount and on demand rather than caching: connections keep
 * syncing in the background, so a feed rendered from stale state would be
 * confidently wrong about what just happened. */
export function FeedModule({ teamId }: { teamId: string }) {
  const [feed, setFeed] = useState<ChannelFeed | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setFeed(await api.get<ChannelFeed>(`/teams/${teamId}/feed`));
    } catch {
      setFeed(null);
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingBlock label="Loading feed" />;

  if (!feed || feed.no_connections) {
    return (
      <EmptyState
        title="No connections assigned"
        description="This channel has no authorized connections yet, so there is nothing to show. An admin assigns them in Extensions."
      />
    );
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-caption text-ink-faint">
          From {feed.connection_labels.length} authorized connection{feed.connection_labels.length === 1 ? "" : "s"}
        </p>
        <Button size="sm" variant="ghost" onClick={load}>
          <Icon name="refresh" size={14} />
          Refresh
        </Button>
      </div>

      {feed.items.length === 0 ? (
        <EmptyState title="Nothing yet" description="No activity has synced into this channel's connections." />
      ) : (
        <div className="rule-rows border-b-0">
          {feed.items.map((item) => (
            <div key={item.id} className="rule-cell-interactive flex items-start gap-3">
              <span className="label-sub mt-px flex-none rounded border border-border px-1.5 py-px">
                {item.type_label}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-body text-ink">{item.title}</div>
                <div className="truncate text-caption text-ink-faint">
                  {item.actor ? `${item.actor} · ` : ""}
                  {item.source_label} · {new Date(item.occurred_at).toLocaleString()}
                </div>
              </div>
              {item.url && (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex-none text-caption text-ink-faint transition-colors hover:text-ink"
                >
                  Open
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
