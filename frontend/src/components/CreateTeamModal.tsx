import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { ChannelPrivacy, Connection, Team, WorkspaceMember } from "../api/types";
import { useAuth } from "../context/AuthContext";
import { useTeams } from "../context/TeamContext";
import { useWorkspace } from "../context/WorkspaceContext";
import { Modal } from "./Modal";

const PRIVACY_OPTIONS: { value: ChannelPrivacy; label: string; desc: string }[] = [
  { value: "public", label: "Public to Group", desc: "Any workspace member can see and join freely" },
  { value: "invite_only", label: "Invite Only", desc: "Visible to the group, but joinable only via invite" },
  { value: "private", label: "Private", desc: "Hidden from everyone except members and group admins" },
];

export function CreateTeamModal({ onClose }: { onClose: () => void }) {
  const { active } = useWorkspace();
  const { refresh } = useTeams();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [icon, setIcon] = useState("");
  const [category, setCategory] = useState("");
  const [privacy, setPrivacy] = useState<ChannelPrivacy>("public");
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [selectedMembers, setSelectedMembers] = useState<Set<string>>(new Set());
  const [selectedAdmins, setSelectedAdmins] = useState<Set<string>>(new Set());
  const [selectedConnections, setSelectedConnections] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    api.get<WorkspaceMember[]>(`/workspaces/${active.id}/members`).then(setMembers).catch(() => setMembers([]));
    api.get<Connection[]>("/connections").then(setConnections).catch(() => setConnections([]));
  }, [active?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  function toggle(set: Set<string>, id: string, apply: (next: Set<string>) => void) {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    apply(next);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!active) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.post<Team>(`/workspaces/${active.id}/teams`, {
        name: name.trim(),
        description: description.trim() || null,
        icon: icon.trim() || null,
        category: category.trim() || null,
        privacy,
        member_user_ids: [...selectedMembers],
        admin_user_ids: [...selectedAdmins],
        connection_ids: [...selectedConnections],
      });
      await refresh();
      onClose();
      navigate(`/channels/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
      setSubmitting(false);
    }
  }

  const otherMembers = members.filter((m) => m.user_id !== user?.id);

  return (
    <Modal title="Create a channel" onClose={onClose}>
      <form onSubmit={handleSubmit} className="max-h-[70vh] overflow-y-auto pr-1">
        {error && <p className="mb-3 border border-crit/30 bg-crit/10 px-3 py-2 text-small text-crit">{error}</p>}

        <div className="mb-3 flex gap-2">
          <input
            value={icon}
            onChange={(e) => setIcon(e.target.value)}
            placeholder="🛠️"
            aria-label="Channel icon (emoji, optional)"
            className="w-14 border border-border bg-ground px-2 py-2.5 text-center text-sub outline-none focus:border-ink"
          />
          <input
            required
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="development"
            className="flex-1 border border-border bg-ground px-3.5 py-2.5 text-body outline-none focus:border-ink"
          />
        </div>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description (optional) — e.g. Workspace for the development team"
          className="mb-3 w-full border border-border bg-ground px-3.5 py-2.5 text-small outline-none focus:border-ink"
        />
        <input
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          placeholder="Category (optional) — e.g. Teams, Projects"
          className="mb-4 w-full border border-border bg-ground px-3.5 py-2.5 text-small outline-none focus:border-ink"
        />

        <div className="label-sub mb-1.5">Privacy</div>
        <div className="mb-4 flex flex-col gap-1.5">
          {PRIVACY_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex cursor-pointer items-start gap-2.5 rounded-md border border-border p-2.5 hover:border-accent">
              <input type="radio" name="privacy" checked={privacy === opt.value} onChange={() => setPrivacy(opt.value)} className="mt-0.5" />
              <span>
                <span className="block text-small font-semibold text-ink">{opt.label}</span>
                <span className="block text-caption text-ink-faint">{opt.desc}</span>
              </span>
            </label>
          ))}
        </div>

        {otherMembers.length > 0 && (
          <>
            <div className="label-sub mb-1.5">
              Members <span className="normal-case tracking-normal">(you're added as Channel Admin automatically)</span>
            </div>
            <div className="mb-4 flex max-h-40 flex-col gap-1 overflow-y-auto">
              {otherMembers.map((m) => (
                <div key={m.user_id} className="flex items-center gap-2.5 rounded-md border border-border px-2.5 py-1.5">
                  <input
                    type="checkbox"
                    checked={selectedMembers.has(m.user_id)}
                    onChange={() => {
                      toggle(selectedMembers, m.user_id, setSelectedMembers);
                      if (selectedAdmins.has(m.user_id)) toggle(selectedAdmins, m.user_id, setSelectedAdmins);
                    }}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-small text-ink">{m.name}</span>
                    <span className="block truncate text-caption text-ink-faint">{m.email}</span>
                  </span>
                  {selectedMembers.has(m.user_id) && (
                    <label className="flex flex-none items-center gap-1 text-micro text-ink-faint">
                      <input
                        type="checkbox"
                        checked={selectedAdmins.has(m.user_id)}
                        onChange={() => toggle(selectedAdmins, m.user_id, setSelectedAdmins)}
                      />
                      admin
                    </label>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {connections.length > 0 && (
          <>
            <div className="label-sub mb-1.5">Connections</div>
            <p className="mb-1.5 text-caption text-ink-faint">
              Assigning a connection grants no resource access by itself — allow-list specific resources afterwards in Channel Settings.
            </p>
            <div className="mb-4 flex flex-col gap-1">
              {connections.map((c) => (
                <label key={c.id} className="flex cursor-pointer items-center gap-2.5 rounded-md border border-border px-2.5 py-1.5">
                  <input
                    type="checkbox"
                    checked={selectedConnections.has(c.id)}
                    onChange={() => toggle(selectedConnections, c.id, setSelectedConnections)}
                  />
                  <span className="text-small text-ink-dim">
                    {c.provider} · {c.org}
                    {c.provider === "github" && c.repo ? `/${c.repo}` : ""}
                  </span>
                </label>
              ))}
            </div>
          </>
        )}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 border border-border py-2.5 text-body text-ink-dim hover:border-crit hover:text-crit"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting || !name.trim()}
            className="flex-1 bg-ink py-2.5 text-body font-semibold text-ground disabled:opacity-40"
          >
            {submitting ? "Creating…" : "Create Channel"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
