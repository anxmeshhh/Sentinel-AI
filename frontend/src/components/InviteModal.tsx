import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { Invite } from "../api/types";
import { Modal } from "./Modal";

type InviteScope = { type: "workspace"; id: string } | { type: "team"; id: string };

export function InviteModal({ scope, label, onClose }: { scope: InviteScope; label: string; onClose: () => void }) {
  const [invite, setInvite] = useState<Invite | null>(null);
  const [generating, setGenerating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      const path = scope.type === "workspace" ? `/workspaces/${scope.id}/invites` : `/teams/${scope.id}/invites`;
      const result = await api.post<Invite>(path, {});
      setInvite(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setGenerating(false);
    }
  }

  const link = invite ? `${window.location.origin}/invite/${invite.token}` : null;

  function copyLink() {
    if (!link) return;
    navigator.clipboard.writeText(link);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <Modal title={`Invite people to ${label}`} onClose={onClose}>
      {error && <p className="mb-3 border border-crit/30 bg-crit/10 px-3 py-2 text-small text-crit">{error}</p>}

      {!invite ? (
        <>
          <p className="mb-4 text-small leading-relaxed text-ink-dim">
            Anyone with this link can join {label} after signing in.
          </p>
          <button
            onClick={generate}
            disabled={generating}
            className="w-full bg-ink py-2.5 text-body font-semibold text-ground disabled:opacity-40"
          >
            {generating ? "Generating…" : "Generate invite link"}
          </button>
        </>
      ) : (
        <>
          <div className="mb-3 flex items-center gap-2 border border-border bg-ground px-3 py-2.5">
            <span className="min-w-0 flex-1 truncate text-small text-ink-dim">{link}</span>
            <button onClick={copyLink} className="flex-none text-small font-semibold text-ink underline underline-offset-2">
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="text-caption text-ink-faint">No expiry, unlimited uses — revoke support coming later.</p>
        </>
      )}
    </Modal>
  );
}
