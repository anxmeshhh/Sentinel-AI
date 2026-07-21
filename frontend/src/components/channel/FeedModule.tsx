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

  if (loading) return <div className="text-[13px] text-ink-dim">Loading feed&hellip;</div>;

  if (!feed || feed.no_connections) {
    return (
      <div className="rounded-md border border-dashed border-border p-8 text-center text-[12.5px] text-ink-faint">
        No connections are assigned to this channel yet, so there's nothing to show. Assign one in Extensions.
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[11px] text-ink-faint">
          From {feed.connection_labels.length} authorized connection{feed.connection_labels.length === 1 ? "" : "s"}
        </p>
        <button onClick={load} className="font-mono text-[10.5px] text-ink-faint underline hover:text-ink">
          Refresh
        </button>
      </div>

      {feed.items.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-8 text-center text-[12.5px] text-ink-faint">
          Nothing has synced into this channel's connections yet.
        </div>
      ) : (
        <div className="flex flex-col divide-y divide-border rounded-md border border-border bg-surface">
          {feed.items.map((item) => (
            <div key={item.id} className="flex items-start gap-3 px-3.5 py-2.5">
              <span className="mt-px flex-none rounded border border-border px-1.5 py-px font-mono text-[9.5px] uppercase text-ink-faint">
                {item.type_label}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12.5px] text-ink">{item.title}</div>
                <div className="truncate text-[10.5px] text-ink-faint">
                  {item.actor ? `${item.actor} · ` : ""}
                  {item.source_label} · {new Date(item.occurred_at).toLocaleString()}
                </div>
              </div>
              {item.url && (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex-none font-mono text-[10px] font-semibold text-accent-text hover:underline"
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
