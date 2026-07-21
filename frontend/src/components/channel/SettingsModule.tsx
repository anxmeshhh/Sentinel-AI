import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, ApiError } from "../../api/client";
import type { ChannelPrivacy, Team } from "../../api/types";
import { useHierarchy } from "../../context/HierarchyContext";
import { useTeams } from "../../context/TeamContext";

/** Channel-level configuration only.
 *
 * Class and Group settings deliberately do not appear here - they belong to
 * their own levels, and folding them in is how a settings screen becomes
 * the cluttered everything-panel this structure exists to avoid. */
export function SettingsModule({ team, onChanged }: { team: Team; onChanged: () => void }) {
  const navigate = useNavigate();
  const { refresh } = useTeams();
  const { refresh: refreshTree } = useHierarchy();
  const [name, setName] = useState(team.name);
  const [description, setDescription] = useState(team.description ?? "");
  const [icon, setIcon] = useState(team.icon ?? "");
  const [privacy, setPrivacy] = useState<ChannelPrivacy>(team.privacy);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await api.patch(`/teams/${team.id}`, { name, description, icon, privacy });
      await Promise.all([refresh(), refreshTree()]);
      onChanged();
      setMessage("Saved.");
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Failed to save");
    } finally {
      setBusy(false);
    }
  }

  async function toggleArchive() {
    const verb = team.is_archived ? "unarchive" : "archive";
    if (
      !team.is_archived &&
      !window.confirm(`Archive #${team.name}? It will be hidden from navigation and Channel AI will be disabled.`)
    )
      return;
    setBusy(true);
    try {
      await api.post(`/teams/${team.id}/${verb}`);
      await Promise.all([refresh(), refreshTree()]);
      onChanged();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : `Failed to ${verb}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteChannel() {
    if (
      !window.confirm(
        `Permanently delete #${team.name}? This removes its members, connection assignments, required integrations and AI history. This cannot be undone.`
      )
    )
      return;
    setBusy(true);
    try {
      await api.delete(`/teams/${team.id}`);
      await Promise.all([refresh(), refreshTree()]);
      navigate("/");
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Failed to delete");
      setBusy(false);
    }
  }

  return (
    <div className="flex max-w-md flex-col gap-3">
      <div className="font-mono text-[10px] uppercase tracking-wide text-ink-faint">General</div>
      <div className="flex gap-1.5">
        <input
          value={icon}
          onChange={(e) => setIcon(e.target.value)}
          placeholder="#"
          aria-label="Channel icon"
          className="w-12 rounded-md border border-border bg-ground px-2 py-1.5 text-center text-[13px] outline-none focus:border-accent"
        />
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="Channel name"
          className="flex-1 rounded-md border border-border bg-ground px-2.5 py-1.5 text-[12.5px] outline-none focus:border-accent"
        />
      </div>
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description"
        className="rounded-md border border-border bg-ground px-2.5 py-1.5 text-[12px] outline-none focus:border-accent"
      />

      <div className="font-mono text-[10px] uppercase tracking-wide text-ink-faint">Privacy</div>
      <select
        value={privacy}
        onChange={(e) => setPrivacy(e.target.value as ChannelPrivacy)}
        aria-label="Channel privacy"
        className="rounded-md border border-border bg-ground px-2.5 py-1.5 text-[12px] outline-none focus:border-accent"
      >
        <option value="public">Public to Group</option>
        <option value="invite_only">Invite Only</option>
        <option value="private">Private</option>
      </select>

      <button
        onClick={save}
        disabled={busy || !name.trim()}
        className="rounded-md bg-accent px-3 py-1.5 font-mono text-[11px] font-bold text-ground disabled:opacity-50"
      >
        {busy ? "Saving…" : "Save changes"}
      </button>
      {message && <p className={`text-[11px] ${message === "Saved." ? "text-good" : "text-crit"}`}>{message}</p>}

      <div className="mt-2 rounded-md border border-crit/30 p-2.5">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-wide text-crit">Danger Zone</div>
        <div className="flex flex-col gap-1.5">
          <button
            onClick={toggleArchive}
            disabled={busy}
            className="text-left text-[11.5px] text-ink-dim underline underline-offset-2 hover:text-watch"
          >
            {team.is_archived ? "Unarchive this channel" : "Archive this channel"}
          </button>
          <button onClick={deleteChannel} disabled={busy} className="text-left text-[11.5px] text-crit underline underline-offset-2">
            Delete this channel permanently
          </button>
        </div>
      </div>
    </div>
  );
}
