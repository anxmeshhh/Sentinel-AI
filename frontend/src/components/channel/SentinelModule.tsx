import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ChannelAIHistoryItem } from "../../api/types";
import { GoogleAICommand } from "../GoogleAICommand";

/** Channel-contextual Sentinel: the orchestrator, scoped to this channel's
 *  authorized connections and resources. */
export function SentinelModule({
  teamId,
  channelName,
  isArchived,
}: {
  teamId: string;
  channelName: string;
  isArchived: boolean;
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
      <div className="rounded-md border border-dashed border-border p-8 text-center text-[12.5px] text-ink-faint">
        Channel AI is disabled while this channel is archived.
      </div>
    );
  }

  return (
    <div>
      <div className="rounded-md border border-border bg-surface">
        <GoogleAICommand
          endpointBase={`/teams/${teamId}/ai`}
          placeholder={`Ask Sentinel about #${channelName}…`}
          helpText={
            <>
              Sentinel only uses Connections and resources authorized for <strong>#{channelName}</strong> — never the rest
              of the Workspace. Actions that change anything are shown as a plan you confirm first.
            </>
          }
        />
      </div>

      {history.length > 0 && (
        <div className="mt-5">
          <div className="mb-2 font-mono text-[11px] uppercase tracking-wide text-ink-faint">Recent activity</div>
          <div className="flex flex-col gap-2">
            {history.slice(0, 10).map((h) => (
              <div key={h.id} className="rounded-md border border-border bg-surface p-3 text-[12px]">
                <div className="mb-1 flex items-center justify-between text-[10.5px] text-ink-faint">
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
