import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ChannelAIHistoryItem } from "../../api/types";
import { SentinelPanel } from "../SentinelPanel";
import { channelContext } from "../context";

/** Channel-contextual Sentinel: the orchestrator, scoped to this channel's
 *  authorized connections and resources. */
export function SentinelModule({
  teamId,
  channelName,
  isArchived,
  className,
  workspaceName,
}: {
  teamId: string;
  channelName: string;
  isArchived: boolean;
  /** The parent Class - a channel inherits its Class's context identity,
   *  because that is the shared boundary its connections belong to. */
  className?: string;
  workspaceName?: string;
}) {
  const [history, setHistory] = useState<ChannelAIHistoryItem[]>([]);

  useEffect(() => {
    api
      .get<ChannelAIHistoryItem[]>(`/teams/${teamId}/ai/history`)
      .then(setHistory)
      .catch(() => setHistory([]));
  }, [teamId]);

  if (isArchived) {
    return (
      <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
        Channel AI is disabled while this channel is archived.
      </div>
    );
  }

  return (
    <div>
      <div className="card overflow-hidden p-0 sm:p-0" style={{ height: 520 }}>
        <SentinelPanel
          endpointBase={`/teams/${teamId}/ai`}
          contextLabel={`#${channelName}`}
          identity={channelContext(className ?? "Channel", channelName, workspaceName)}
          placeholder={`Ask Sentinel about #${channelName}…`}
          suggestions={[
            "What needs this channel's attention right now?",
            "Summarize the latest activity here",
          ]}
        />
      </div>

      {history.length > 0 && (
        <div className="mt-5">
          <div className="label-sub mb-2">Recent activity</div>
          <div className="flex flex-col gap-2">
            {history.slice(0, 10).map((h) => (
              <div key={h.id} className="card p-3 text-small">
                <div className="mb-1 flex items-center justify-between text-caption text-ink-faint">
                  <span>{h.user_name}</span>
                  <span>{new Date(h.created_at).toLocaleString()}</span>
                </div>
                <div className="mb-1 font-semibold text-ink">{h.command}</div>
                <div className="line-clamp-3 text-ink-dim">{h.reply}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
