import type { FormEvent } from "react";
import { useState } from "react";

import { ApiError, api } from "../api/client";
import type { Workspace } from "../context/WorkspaceContext";
import { Modal } from "./Modal";

export function CreateWorkspaceModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  // May be async: the caller refreshes the workspace list before switching
  // to the new workspace, and the modal should stay in its submitting state
  // until that finishes rather than closing over a half-applied switch.
  onCreated: (workspace: Workspace) => void | Promise<void>;
}) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const workspace = await api.post<Workspace>("/workspaces", { name });
      await onCreated(workspace);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title="Create a workspace" onClose={onClose}>
      <p className="mb-4 text-small leading-relaxed text-ink-dim">
        A new server for your team — channels and members live inside it, separate from your
        Personal workspace.
      </p>
      <form onSubmit={handleSubmit}>
        {error && <p className="mb-3 border border-crit/30 bg-crit/10 px-3 py-2 text-small text-crit">{error}</p>}
        <input
          required
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Acme Corporation"
          className="mb-4 w-full border border-border bg-ground px-3.5 py-2.5 text-body outline-none focus:border-ink"
        />
        <button
          type="submit"
          disabled={submitting || !name.trim()}
          className="w-full bg-ink py-2.5 text-body font-semibold text-ground disabled:opacity-40"
        >
          {submitting ? "Creating…" : "Create workspace"}
        </button>
      </form>
    </Modal>
  );
}
