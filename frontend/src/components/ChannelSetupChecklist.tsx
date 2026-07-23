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
  needs_setup: {
    label: "Needs setup",
    tone: "text-watch",
    hint: "Connected, but not pointed at anything yet - pick a repository to finish.",
  },
};

/** Where an admin shared it, in the member's words. The API returns a tier
 *  name and nothing else - whose account it is stays deliberately unsaid. */
const PROVIDED_BY_COPY: Record<string, string> = {
  workspace: "shared across this workspace",
  class: "shared with this class",
  group: "shared with this group",
  channel: "shared with this channel",
};

/**
 * A member's own setup checklist for a channel.
 *
 * Two different things can satisfy a requirement, and the distinction is the
 * whole point of this screen:
 *
 *   - An admin shared that service with the channel. Nothing to do. The
 *     channel reads the admin's account, exactly as it did before this
 *     member arrived.
 *   - Nobody shared it, so this member's own account is the only way the
 *     channel gets that context, and they are asked for it.
 *
 * Anything a member connects here is theirs: it feeds their own Sentinel and
 * never becomes channel context (the resolver reads shared connections only).
 * That is why the optional path below is labelled private rather than dressed
 * up as a contribution to the team.
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
  const [showCovered, setShowCovered] = useState(false);

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
  const provided = readiness.requirements.filter((r) => r.provided_by !== null);
  const outstanding = readiness.requirements.filter((r) => r.provided_by === null);

  // Once nothing is outstanding, the covered rows collapse behind a line: a
  // member with no work to do should learn that in one sentence rather than
  // read a checklist of things somebody else already handled.
  const nothingToDo = outstanding.length === 0;
  const visibleProvided = nothingToDo && !showCovered ? [] : provided;

  return (
    <div className={`mb-4 rounded-md border p-4 ${blocked ? "border-watch/40 bg-watch/5" : "border-border bg-surface"}`}>
      <div className="label-sub mb-1 font-bold text-ink-dim">
        {blocked ? "Finish setting up this channel" : "Your channel setup"}
      </div>
      <p className="mb-3 text-caption leading-relaxed text-ink-faint">
        {blocked
          ? "This channel still needs the integrations below. You connect your own account — nobody else in the channel can see it, and it isn't shared with them."
          : nothingToDo
            ? "Nothing to do — an admin already connected everything this channel needs."
            : "You're set up for this channel. These are your own accounts, visible only to you."}
      </p>

      {(outstanding.length > 0 || visibleProvided.length > 0) && (
        <div className="flex flex-col gap-2">
          {outstanding.map((r) => (
            <ChecklistRow key={r.provider} status={r} busy={busy} onConnectGoogle={connectGoogle} />
          ))}
          {visibleProvided.map((r) => (
            <ChecklistRow key={r.provider} status={r} busy={busy} onConnectGoogle={connectGoogle} />
          ))}
        </div>
      )}

      {nothingToDo && (
        <button
          onClick={() => setShowCovered((v) => !v)}
          className="text-caption text-ink-faint underline hover:text-ink-dim"
        >
          {showCovered ? "Hide details" : `Show what's already connected (${provided.length})`}
        </button>
      )}
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
  const isProvided = status.provided_by !== null;
  const needsAction =
    !isProvided &&
    (status.state === "not_connected" || status.state === "expired" || status.state === "needs_setup");
  const isGoogle = GOOGLE_PROVIDERS.has(status.provider);

  return (
    <div className="rounded-md border border-border bg-ground px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="text-small font-semibold text-ink">{PROVIDER_LABEL[status.provider] ?? status.provider}</span>
          {!status.is_required && (
            <span className="ml-2 rounded-full border border-border px-1.5 py-px text-micro text-ink-faint">OPTIONAL</span>
          )}
          {/* Only ever the viewer's own account - the API sends no other, and
              an admin's address is never named on this screen. */}
          {status.account_label && <div className="truncate text-caption text-ink-faint">{status.account_label}</div>}
        </div>
        <div className="flex flex-none items-center gap-2.5">
          <span className={`font-mono text-caption ${isProvided ? "text-good" : copy.tone}`}>
            {isProvided ? "Provided" : copy.label}
          </span>
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

      {isProvided ? (
        <ProvidedNote status={status} isGoogle={isGoogle} busy={busy} onConnectGoogle={onConnectGoogle} />
      ) : (
        copy.hint && <p className="mt-1 text-caption leading-relaxed text-ink-faint">{copy.hint}</p>
      )}
    </div>
  );
}

/** What a covered requirement means, plus the optional private path beside it.
 *  Both halves matter: the member is told they are done, and told that
 *  connecting anyway buys them something that stays theirs. */
function ProvidedNote({
  status,
  isGoogle,
  busy,
  onConnectGoogle,
}: {
  status: RequirementStatus;
  isGoogle: boolean;
  busy: boolean;
  onConnectGoogle: () => void;
}) {
  const where = PROVIDED_BY_COPY[status.provided_by ?? ""] ?? "shared with this channel";
  const label = PROVIDER_LABEL[status.provider] ?? status.provider;
  const alreadyMine = status.state === "ready" || status.state === "syncing";

  return (
    <div className="mt-1">
      <p className="text-caption leading-relaxed text-ink-faint">
        An admin already connected this — it's {where}. You don't need to connect your own.
      </p>
      {alreadyMine ? (
        <p className="mt-1 text-caption leading-relaxed text-ink-faint">
          🔒 You've also connected your own {label}. It stays private — it feeds your Attention only, and this channel
          never reads it.
        </p>
      ) : (
        <p className="mt-1 text-caption leading-relaxed text-ink-faint">
          🔒 Optional: connect your own {label} to sharpen your personal Attention. Only you can see it — it is never
          shared with this channel or its admins.{" "}
          {isGoogle ? (
            <button onClick={onConnectGoogle} disabled={busy} className="underline hover:text-ink-dim disabled:opacity-50">
              Connect privately
            </button>
          ) : (
            <Link to={`/connections/${status.provider}`} className="underline hover:text-ink-dim">
              Connect privately
            </Link>
          )}
        </p>
      )}
    </div>
  );
}
