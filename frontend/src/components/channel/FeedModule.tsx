import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ChannelFeed } from "../../api/types";

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

  if (loading) return <div className="text-body text-ink-dim">Loading feed&hellip;</div>;

  if (!feed || feed.no_connections) {
    return (
      <div className="rounded-md border border-dashed border-border-strong p-8 text-center text-small text-ink-faint">
        No connections are assigned to this channel yet, so there's nothing to show. Assign one in Extensions.
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-caption text-ink-faint">
          From {feed.connection_labels.length} authorized connection{feed.connection_labels.length === 1 ? "" : "s"}
        </p>
        <button onClick={load} className="text-caption text-ink-faint underline hover:text-ink">
          Refresh
        </button>
      </div>

      {feed.items.length === 0 ? (
        <div className="rounded-md border border-dashed border-border-strong p-8 text-center text-small text-ink-faint">
          Nothing has synced into this channel's connections yet.
        </div>
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
                  className="flex-none text-micro font-semibold text-accent-text hover:underline"
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
