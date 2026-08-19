import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, ApiError } from "../../api/client";
import type { ChannelPrivacy, Team } from "../../api/types";
import { useHierarchy } from "../../context/HierarchyContext";
import { useTeams } from "../../context/TeamContext";
import { Button } from "../ui";

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
      <div className="label-sub">General</div>
      <div className="flex gap-1.5">
        <input
          value={icon}
          onChange={(e) => setIcon(e.target.value)}
          placeholder="#"
          aria-label="Channel icon"
          className="w-12 text-center rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
        />
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="Channel name"
          className="flex-1 rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Description"
        className="rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
      />

      <div className="label-sub">Privacy</div>
      <select
        value={privacy}
        onChange={(e) => setPrivacy(e.target.value as ChannelPrivacy)}
        aria-label="Channel privacy"
        className="rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <option value="public">Public to Group</option>
        <option value="invite_only">Invite Only</option>
        <option value="private">Private</option>
      </select>

      <Button size="sm" variant="primary" onClick={save} disabled={busy || !name.trim()}>
        {busy ? "Saving…" : "Save changes"}
      </Button>
      {message && <p className={`text-caption ${message === "Saved." ? "text-good" : "text-crit"}`}>{message}</p>}

      <div className="mt-2 rounded-md border border-crit/30 p-2.5">
        <div className="label-sub mb-2 text-crit">Danger Zone</div>
        <div className="flex flex-col gap-1.5">
          <Button size="sm" variant="secondary" onClick={toggleArchive} disabled={busy}>
            {team.is_archived ? "Unarchive this channel" : "Archive this channel"}
          </Button>
          <Button size="sm" variant="danger" onClick={deleteChannel} disabled={busy}>
            Delete this channel permanently
          </Button>
        </div>
      </div>
    </div>
  );
}
