import type { FormEvent } from "react";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import { useTeams } from "../context/TeamContext";
import { useWorkspace } from "../context/WorkspaceContext";
import { Modal } from "./Modal";

export function CreateTeamModal({ onClose }: { onClose: () => void }) {
  const { active } = useWorkspace();
  const { refresh } = useTeams();
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!active) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.post(`/workspaces/${active.id}/teams`, { name });
      await refresh();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="Create a channel" onClose={onClose}>
      <p className="mb-4 text-[12.5px] leading-relaxed text-ink-dim">
        Any member of this workspace can join — channels are open by default, like a public
        Discord channel.
      </p>
      <form onSubmit={handleSubmit}>
        {error && <p className="mb-3 border border-crit/30 bg-crit/10 px-3 py-2 text-[12.5px] text-crit">{error}</p>}
        <input
          required
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Backend Team"
          className="mb-4 w-full border border-border bg-ground px-3.5 py-2.5 text-[13.5px] outline-none focus:border-ink"
        />
        <button
          type="submit"
          disabled={submitting || !name.trim()}
          className="w-full bg-ink py-2.5 text-[13.5px] font-semibold text-ground disabled:opacity-40"
        >
          {submitting ? "Creating…" : "Create channel"}
        </button>
      </form>
    </Modal>
  );
}
