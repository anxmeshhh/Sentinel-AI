import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { ChannelReadiness, ReadinessState, RequirementStatus } from "../api/types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const PROVIDER_LABEL: Record<string, string> = {
  gmail: "Gmail",
  google_calendar: "Google Calendar",
  google_drive: "Google Drive",
  github: "GitHub",
};

const GOOGLE_PROVIDERS = new Set(["gmail", "google_calendar", "google_drive"]);

/** Each state says what is true and what to do about it - a raw enum on
 *  screen ("syncing") leaves the member guessing whether to wait or act. */
const STATE_COPY: Record<ReadinessState, { label: string; tone: string; hint: string }> = {
  ready: { label: "Connected", tone: "text-good", hint: "" },
  syncing: {
    label: "Syncing",
    tone: "text-watch",
    hint: "Connected — Sentinel is reading your first batch of data. This usually takes a minute.",
  },
  expired: {
    label: "Reconnect needed",
    tone: "text-crit",
    hint: "Access was revoked or expired, so Sentinel can no longer read this. Reconnecting fixes it.",
  },
  not_connected: { label: "Not connected", tone: "text-ink-faint", hint: "" },
};

/**
 * A member's own setup checklist for a channel.
 *
 * The requirement was set by an admin; the account is always the viewer's.
 * Nothing here can show or act on anyone else's connection - the endpoint
 * behind it takes no user parameter at all.
 */
export function ChannelSetupChecklist({
  readiness,
  teamId,
  workspaceId,
  compact = false,
}: {
  readiness: ChannelReadiness;
  teamId: string;
  workspaceId: string;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState(false);

  if (readiness.requirements.length === 0) return null;
  if (compact && readiness.is_ready) return null;

  async function connectGoogle() {
    setBusy(true);
    try {
      const { ticket } = await api.post<{ ticket: string }>("/integrations/google/connect-ticket", undefined, { workspaceId });
      const returnTo = encodeURIComponent(`/channels/${teamId}`);
      window.location.href = `${API_BASE}/integrations/google/connect?ticket=${encodeURIComponent(ticket)}&return_to=${returnTo}`;
    } catch {
      setBusy(false);
    }
  }

  const blocked = !readiness.is_ready;

  return (
    <div className={`mb-4 rounded-md border p-4 ${blocked ? "border-watch/40 bg-watch/5" : "border-border bg-surface"}`}>
      <div className="label-sub mb-1 font-bold text-ink-dim">
        {blocked ? "Finish setting up this channel" : "Your channel setup"}
      </div>
      <p className="mb-3 text-caption leading-relaxed text-ink-faint">
        {blocked
          ? "This channel needs the integrations below. You connect your own account — nobody else in the channel can see it, and it isn't shared with them."
          : "You're connected. These are your own accounts, visible only to you."}
      </p>

      <div className="flex flex-col gap-2">
        {readiness.requirements.map((r) => (
          <ChecklistRow key={r.provider} status={r} busy={busy} onConnectGoogle={connectGoogle} />
        ))}
      </div>
    </div>
  );
}

function ChecklistRow({
  status,
  busy,
  onConnectGoogle,
}: {
  status: RequirementStatus;
  busy: boolean;
  onConnectGoogle: () => void;
}) {
  const copy = STATE_COPY[status.state];
  const needsAction = status.state === "not_connected" || status.state === "expired";
  const isGoogle = GOOGLE_PROVIDERS.has(status.provider);

  return (
    <div className="rounded-md border border-border bg-ground px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="text-small font-semibold text-ink">{PROVIDER_LABEL[status.provider] ?? status.provider}</span>
          {!status.is_required && (
            <span className="ml-2 rounded-full border border-border px-1.5 py-px text-micro text-ink-faint">OPTIONAL</span>
          )}
          {status.account_label && <div className="truncate text-caption text-ink-faint">{status.account_label}</div>}
        </div>
        <div className="flex flex-none items-center gap-2.5">
          <span className={`font-mono text-caption ${copy.tone}`}>{copy.label}</span>
          {needsAction &&
            (isGoogle ? (
              <button
                onClick={onConnectGoogle}
                disabled={busy}
                className="btn-primary"
              >
                {status.state === "expired" ? "Reconnect" : "Connect"}
              </button>
            ) : (
              <Link
                to={`/connections/${status.provider}`}
                className="btn-primary"
              >
                {status.state === "expired" ? "Reconnect" : "Connect"}
              </Link>
            ))}
        </div>
      </div>
      {/* The admin's reason, then the state's own explanation - a member
          being asked for mailbox access is owed both. */}
      {status.reason && <p className="mt-1 text-caption leading-relaxed text-ink-dim">{status.reason}</p>}
      {copy.hint && <p className="mt-1 text-caption leading-relaxed text-ink-faint">{copy.hint}</p>}
    </div>
  );
}
