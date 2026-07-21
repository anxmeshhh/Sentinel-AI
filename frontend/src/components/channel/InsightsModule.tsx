import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ChannelInsights } from "../../api/types";
import { Card, EmptyState, LoadingBlock } from "../ui";

/** Operational intelligence for the channel: activity volume, cadence, and
 *  who's most active - every number a deterministic count over the signals
 *  this channel is authorized to see. No LLM, nothing invented. */
export function InsightsModule({ teamId }: { teamId: string }) {
  const [data, setData] = useState<ChannelInsights | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.get<ChannelInsights>(`/teams/${teamId}/insights`));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingBlock />;
  if (!data || data.no_connections) {
    return (
      <EmptyState
        title="No insights yet"
        description="Insights are computed from this channel's authorized connections. Assign one in Extensions and activity will start showing here."
      />
    );
  }
  if (data.total === 0) {
    return (
      <EmptyState
        title="Nothing in the last 30 days"
        description="This channel's connections are assigned but haven't synced any activity in the window yet."
      />
    );
  }

  const max = Math.max(...data.by_type.map((t) => t.count), 1);

  return (
    <div className="flex flex-col gap-6">
      <p className="text-caption text-ink-faint">
        {data.total} events across {data.connection_labels.length} connection
        {data.connection_labels.length === 1 ? "" : "s"} in the last {data.window_days} days.
      </p>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <div className="text-caption text-ink-faint">Total activity</div>
          <div className="mt-1 text-h2 font-medium tabular-nums text-ink">{data.total}</div>
        </Card>
        <Card>
          <div className="text-caption text-ink-faint">Busiest day</div>
          <div className="mt-1 text-h3 font-medium text-ink">
            {data.busiest_day ? new Date(data.busiest_day.date).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "—"}
          </div>
          {data.busiest_day && <div className="text-caption text-ink-faint">{data.busiest_day.count} events</div>}
        </Card>
        <Card>
          <div className="text-caption text-ink-faint">Activity types</div>
          <div className="mt-1 text-h3 font-medium text-ink">{data.by_type.length}</div>
        </Card>
      </div>

      {/* Volume by type - a plain horizontal bar per type, width proportional
          to count. Deterministic, no charting library. */}
      <section>
        <h2 className="mb-3 text-title font-medium text-ink">Activity by type</h2>
        <div className="flex flex-col gap-2">
          {data.by_type.map((t) => (
            <div key={t.type} className="flex items-center gap-3">
              <span className="w-28 flex-none text-caption text-ink-dim">{t.label}</span>
              <div className="h-5 flex-1 overflow-hidden rounded-sm bg-surface-2">
                <div className="h-full rounded-sm bg-ink/70" style={{ width: `${(t.count / max) * 100}%` }} />
              </div>
              <span className="w-8 flex-none text-right text-caption tabular-nums text-ink-dim">{t.count}</span>
            </div>
          ))}
        </div>
      </section>

      {data.top_actors.length > 0 && (
        <section>
          <h2 className="mb-3 text-title font-medium text-ink">Most active</h2>
          <div className="rule-rows border-t border-rule">
            {data.top_actors.map((a) => (
              <div key={a.actor} className="flex items-center justify-between">
                <span className="min-w-0 flex-1 truncate text-caption text-ink-dim">{a.actor}</span>
                <span className="flex-none text-caption tabular-nums text-ink-faint">{a.count}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
