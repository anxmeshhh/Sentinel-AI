import { Link } from "react-router-dom";

import type { Connection } from "../api/types";

const PROVIDER_LABEL: Record<Connection["provider"], string> = {
  github: "GitHub",
  google_calendar: "Calendar",
  gmail: "Gmail",
};

// Freshness beyond this is shown as stale (amber), not just "synced" (green) -
// a connection that's stopped syncing should be visible at a glance, not buried.
const STALE_AFTER_HOURS = 6;

export function ConnectedSourcesStrip({ connections }: { connections: Connection[] }) {
  if (connections.length === 0) {
    return (
      <div className="mb-5 flex items-center justify-between rounded-md border border-dashed border-border px-3.5 py-2.5 text-[12.5px] text-ink-faint">
        <span>Nothing connected yet.</span>
        <Link to="/settings" className="font-semibold text-accent-text underline underline-offset-2">
          Connect a source &rarr;
        </Link>
      </div>
    );
  }

  return (
    <div className="mb-5 flex flex-wrap items-center gap-2">
      {connections.map((c) => (
        <SourceChip key={c.id} connection={c} />
      ))}
      <Link
        to="/settings"
        className="ml-1 font-mono text-[11px] text-ink-faint underline underline-offset-2 hover:text-ink"
      >
        + manage
      </Link>
    </div>
  );
}

function SourceChip({ connection }: { connection: Connection }) {
  const status = _status(connection.last_synced_at);
  const dotClass = status === "never" ? "bg-ink-faint" : status === "stale" ? "bg-watch" : "bg-good";
  return (
    <div className="flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1">
      <span className={`h-1.5 w-1.5 flex-none rounded-full ${dotClass}`} />
      <span className="font-mono text-[11px] font-semibold text-ink-dim">{PROVIDER_LABEL[connection.provider]}</span>
      <span className="font-mono text-[10.5px] text-ink-faint">
        {connection.last_synced_at ? `synced ${_relativeTime(connection.last_synced_at)}` : "not synced yet"}
      </span>
    </div>
  );
}

function _status(lastSyncedAt: string | null): "never" | "stale" | "fresh" {
  if (!lastSyncedAt) return "never";
  const hours = (Date.now() - new Date(lastSyncedAt).getTime()) / 3_600_000;
  return hours > STALE_AFTER_HOURS ? "stale" : "fresh";
}

function _relativeTime(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}
