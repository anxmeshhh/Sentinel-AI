import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { ChannelAIHistoryItem, ChannelConnection, ChannelPrivacy, Connection, Team, TeamMember } from "../api/types";
import { BackNav } from "../components/BackNav";
import { GoogleAICommand } from "../components/GoogleAICommand";
import { useTeams } from "../context/TeamContext";

type PanelTab = "connections" | "members" | "activity" | "settings";

export function ChannelWorkspacePage() {
  const { teamId = "" } = useParams<{ teamId: string }>();
  const [team, setTeam] = useState<Team | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [connections, setConnections] = useState<ChannelConnection[]>([]);
  const [history, setHistory] = useState<ChannelAIHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [panelTab, setPanelTab] = useState<PanelTab>("connections");

  const isAdmin = team?.my_channel_role === "channel_admin";

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const [t, m, c] = await Promise.all([
        api.get<Team>(`/teams/${teamId}`),
        api.get<TeamMember[]>(`/teams/${teamId}/members`),
        api.get<ChannelConnection[]>(`/teams/${teamId}/connections`),
      ]);
      setTeam(t);
      setMembers(m);
      setConnections(c);
      // Deliberately NOT switching the global active workspace here - an
      // earlier version did, and silently flipping it made the user's
      // Mail/Calendar/Drive pages (scoped to their Personal workspace) go
      // blank after visiting any org channel. The one call that needs this
      // channel's workspace (the connection picker) passes it explicitly.
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load this channel");
    } finally {
      setLoading(false);
    }
  }

  async function loadHistory() {
    try {
      setHistory(await api.get<ChannelAIHistoryItem[]>(`/teams/${teamId}/ai/history`));
    } catch {
      setHistory([]);
    }
  }

  useEffect(() => {
    void loadAll();
    void loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamId]);

  if (loading) return <div className="text-ink-dim">Loading&hellip;</div>;
  if (error || !team) {
    return (
      <div className="max-w-lg rounded-md border border-dashed border-border p-10 text-center text-ink-dim">
        <BackNav back={{ to: "/", label: "Dashboard" }} />
        <p className="text-[14px] text-crit">{error ?? "Channel not found."}</p>
      </div>
    );
  }

  return (
    <div className="max-w-6xl">
      <BackNav back={{ to: "/", label: "Dashboard" }} crumbs={[{ label: "Dashboard", to: "/" }, { label: `#${team.name}` }]} />

      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="mb-1 text-xl font-semibold text-balance">
            {team.icon ? `${team.icon} ` : ""}#{team.name}
          </h1>
          {team.description && <p className="mb-1 text-[13px] text-ink-dim">{team.description}</p>}
          <p className="text-[13px] text-ink-dim">
            {team.member_count} member{team.member_count === 1 ? "" : "s"}
            {team.category && <span className="ml-2 font-mono text-[10.5px] text-ink-faint">{team.category}</span>}
            {team.privacy !== "public" && (
              <span className="ml-2 rounded-full border border-border px-2 py-0.5 font-mono text-[10px] text-ink-faint">
                {team.privacy === "private" ? "PRIVATE" : "INVITE ONLY"}
              </span>
            )}
            {isAdmin && <span className="ml-2 rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 font-mono text-[10px] text-accent-text">CHANNEL ADMIN</span>}
          </p>
        </div>
        <div className="flex gap-2">
          {isAdmin && (
            <button
              onClick={() => {
                setPanelOpen(true);
                setPanelTab("settings");
              }}
              className="rounded-md border border-border bg-surface px-3 py-1.5 font-mono text-[11.5px] text-ink-dim hover:border-accent hover:text-ink"
            >
              ⚙ Channel Settings
            </button>
          )}
          <button
            onClick={() => setPanelOpen((o) => !o)}
            className="rounded-md border border-border bg-surface px-3 py-1.5 font-mono text-[11.5px] text-ink-dim hover:border-accent hover:text-ink"
          >
            {panelOpen ? "Hide" : "Show"} channel info
          </button>
        </div>
      </div>

      {team.is_archived && (
        <div className="mb-4 rounded-md border border-watch/40 bg-watch/5 px-4 py-3 text-[12.5px] text-watch">
          This channel is archived — Channel AI is disabled and it's hidden from the sidebar.
          {isAdmin && " Unarchive it from Channel Settings to bring it back."}
        </div>
      )}

      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 flex-1">
          {connections.length === 0 ? (
            <div className="mb-4 rounded-md border border-dashed border-border p-6 text-center text-[13px] text-ink-faint">
              No Connections are assigned to this channel yet.
              {isAdmin ? " Assign one from the panel to start using Channel AI here." : " Ask a Channel Admin to assign one."}
            </div>
          ) : (
            <div className="mb-4 flex flex-wrap gap-1.5">
              {connections.map((c) => (
                <span key={c.id} className="rounded-full border border-border px-2.5 py-1 font-mono text-[10.5px] text-ink-faint">
                  {c.provider} · {c.label}
                </span>
              ))}
            </div>
          )}

          {!team.is_archived && (
            <div className="rounded-md border border-border bg-surface">
              <GoogleAICommand
                endpointBase={`/teams/${teamId}/ai`}
                placeholder={`Ask Sentinel about #${team.name}…`}
                helpText={
                  <>
                    Sentinel only uses Connections and resources authorized for <strong>#{team.name}</strong> - never the rest of the
                    Workspace. Actions that change anything are shown as a plan you confirm first.
                  </>
                }
              />
            </div>
          )}

          {history.length > 0 && (
            <div className="mt-5">
              <div className="mb-2 font-mono text-[11px] uppercase tracking-wide text-ink-faint">Recent Channel AI Activity</div>
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

        {panelOpen && (
          <div className="w-full flex-none lg:w-[340px]">
            <div className="rounded-md border border-border bg-surface">
              <div className="flex border-b border-border">
                {(["connections", "members", "activity", ...(isAdmin ? (["settings"] as PanelTab[]) : [])] as PanelTab[]).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setPanelTab(tab)}
                    className={`flex-1 py-2.5 text-center font-mono text-[10.5px] uppercase tracking-wide transition-colors ${
                      panelTab === tab ? "text-ink" : "text-ink-faint hover:text-ink-dim"
                    }`}
                    style={panelTab === tab ? { borderBottom: "2px solid var(--accent, #7c9)" } : undefined}
                  >
                    {tab === "settings" ? "⚙" : tab}
                  </button>
                ))}
              </div>
              <div className="p-3.5">
                {panelTab === "connections" && (
                  <ConnectionsTab teamId={teamId} workspaceId={team.workspace_id} isAdmin={isAdmin} connections={connections} onChanged={loadAll} />
                )}
                {panelTab === "members" && <MembersTab teamId={teamId} isAdmin={isAdmin} members={members} onChanged={loadAll} />}
                {panelTab === "activity" && <ActivityTab history={history} />}
                {panelTab === "settings" && isAdmin && <SettingsTab team={team} onChanged={loadAll} />}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ConnectionsTab({
  teamId,
  workspaceId,
  isAdmin,
  connections,
  onChanged,
}: {
  teamId: string;
  workspaceId: string;
  isAdmin: boolean;
  connections: ChannelConnection[];
  onChanged: () => void;
}) {
  const [available, setAvailable] = useState<Connection[]>([]);
  const [showPicker, setShowPicker] = useState(false);
  const [busy, setBusy] = useState(false);
  const [resourceForm, setResourceForm] = useState<Record<string, { key: string; label: string }>>({});

  useEffect(() => {
    if (!showPicker) return;
    api.get<Connection[]>("/connections", { workspaceId }).then(setAvailable).catch(() => setAvailable([]));
  }, [showPicker, workspaceId]);

  const assignedConnectionIds = new Set(connections.map((c) => c.connection_id));
  const assignable = available.filter((c) => !assignedConnectionIds.has(c.id));

  async function assign(connectionId: string) {
    setBusy(true);
    try {
      await api.post(`/teams/${teamId}/connections`, { connection_id: connectionId });
      setShowPicker(false);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function unassign(channelConnectionId: string) {
    setBusy(true);
    try {
      await api.delete(`/teams/${teamId}/connections/${channelConnectionId}`);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function addResource(channelConnectionId: string) {
    const form = resourceForm[channelConnectionId];
    if (!form?.key.trim() || !form?.label.trim()) return;
    setBusy(true);
    try {
      await api.post(`/teams/${teamId}/connections/${channelConnectionId}/resources`, {
        resource_key: form.key.trim(),
        resource_label: form.label.trim(),
      });
      setResourceForm((f) => ({ ...f, [channelConnectionId]: { key: "", label: "" } }));
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function removeResource(channelConnectionId: string, resourceId: string) {
    setBusy(true);
    try {
      await api.delete(`/teams/${teamId}/connections/${channelConnectionId}/resources/${resourceId}`);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {connections.length === 0 && <p className="text-[12px] text-ink-faint">No connections assigned.</p>}
      {connections.map((c) => (
        <div key={c.id} className="rounded-md border border-border p-2.5">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[12.5px] font-semibold text-ink">
              {c.provider} · {c.label}
            </span>
            {isAdmin && (
              <button onClick={() => unassign(c.id)} disabled={busy} className="text-[10.5px] text-ink-faint underline hover:text-crit">
                Remove
              </button>
            )}
          </div>
          <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wide text-ink-faint">Allow-listed resources</div>
          {c.resources.length === 0 ? (
            <p className="mb-1.5 text-[11px] text-ink-faint">None yet - nothing here is usable by Channel AI until a resource is added.</p>
          ) : (
            <div className="mb-1.5 flex flex-col gap-1">
              {c.resources.map((r) => (
                <div key={r.id} className="flex items-center justify-between text-[11.5px] text-ink-dim">
                  <span className="truncate">{r.resource_label}</span>
                  {isAdmin && (
                    <button onClick={() => removeResource(c.id, r.id)} disabled={busy} className="text-[10px] text-ink-faint underline hover:text-crit">
                      Remove
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          {isAdmin && (
            <div className="flex gap-1.5">
              <input
                value={resourceForm[c.id]?.key ?? ""}
                onChange={(e) => setResourceForm((f) => ({ ...f, [c.id]: { key: e.target.value, label: f[c.id]?.label ?? "" } }))}
                placeholder="resource id/key"
                className="w-1/2 rounded-md border border-border bg-ground px-2 py-1 text-[11px] outline-none focus:border-accent"
              />
              <input
                value={resourceForm[c.id]?.label ?? ""}
                onChange={(e) => setResourceForm((f) => ({ ...f, [c.id]: { key: f[c.id]?.key ?? "", label: e.target.value } }))}
                placeholder="display name"
                className="w-1/2 rounded-md border border-border bg-ground px-2 py-1 text-[11px] outline-none focus:border-accent"
              />
              <button
                onClick={() => addResource(c.id)}
                disabled={busy}
                className="flex-none rounded-md bg-accent px-2.5 py-1 font-mono text-[10.5px] font-bold text-ground disabled:opacity-50"
              >
                Add
              </button>
            </div>
          )}
        </div>
      ))}

      {isAdmin && (
        <div>
          {!showPicker ? (
            <button onClick={() => setShowPicker(true)} className="font-mono text-[11px] text-ink-faint underline hover:text-ink">
              + Assign a connection
            </button>
          ) : (
            <div className="rounded-md border border-dashed border-border p-2.5">
              {assignable.length === 0 ? (
                <p className="text-[11px] text-ink-faint">No more workspace connections available to assign.</p>
              ) : (
                assignable.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => assign(c.id)}
                    disabled={busy}
                    className="block w-full rounded-md px-2 py-1.5 text-left text-[11.5px] text-ink-dim hover:bg-surface-2 hover:text-ink"
                  >
                    {c.provider} · {c.org}
                    {c.repo && c.provider === "github" ? `/${c.repo}` : ""}
                  </button>
                ))
              )}
              <button onClick={() => setShowPicker(false)} className="mt-1 font-mono text-[10.5px] text-ink-faint underline hover:text-ink">
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MembersTab({
  teamId,
  isAdmin,
  members,
  onChanged,
}: {
  teamId: string;
  isAdmin: boolean;
  members: TeamMember[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function setRole(userId: string, role: "channel_admin" | "channel_member") {
    setBusy(true);
    try {
      await api.patch(`/teams/${teamId}/members/${userId}/role`, { channel_role: role });
      onChanged();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "Failed to update role");
    } finally {
      setBusy(false);
    }
  }

  async function remove(userId: string) {
    setBusy(true);
    try {
      await api.delete(`/teams/${teamId}/members/${userId}`);
      onChanged();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "Failed to remove member");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {members.map((m) => (
        <div key={m.user_id} className="flex items-center justify-between text-[12px]">
          <div className="min-w-0">
            <div className="truncate text-ink">{m.name}</div>
            <div className="truncate text-[10.5px] text-ink-faint">{m.email}</div>
          </div>
          <div className="flex flex-none items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 font-mono text-[10px] ${
                m.channel_role === "channel_admin" ? "bg-accent/15 text-accent-text" : "text-ink-faint"
              }`}
            >
              {m.channel_role === "channel_admin" ? "admin" : "member"}
            </span>
            {isAdmin && (
              <>
                <button
                  onClick={() => setRole(m.user_id, m.channel_role === "channel_admin" ? "channel_member" : "channel_admin")}
                  disabled={busy}
                  className="text-[10.5px] text-ink-faint underline hover:text-ink"
                >
                  {m.channel_role === "channel_admin" ? "Demote" : "Promote"}
                </button>
                <button onClick={() => remove(m.user_id)} disabled={busy} className="text-[10.5px] text-ink-faint underline hover:text-crit">
                  Remove
                </button>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function SettingsTab({ team, onChanged }: { team: Team; onChanged: () => void }) {
  const navigate = useNavigate();
  const { refresh } = useTeams();
  const [name, setName] = useState(team.name);
  const [description, setDescription] = useState(team.description ?? "");
  const [icon, setIcon] = useState(team.icon ?? "");
  const [category, setCategory] = useState(team.category ?? "");
  const [privacy, setPrivacy] = useState<ChannelPrivacy>(team.privacy);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await api.patch(`/teams/${team.id}`, { name, description, icon, category, privacy });
      await refresh();
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
    if (!team.is_archived && !window.confirm(`Archive #${team.name}? It will be hidden from the sidebar and Channel AI will be disabled. You can unarchive it later.`)) return;
    setBusy(true);
    try {
      await api.post(`/teams/${team.id}/${verb}`);
      await refresh();
      onChanged();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : `Failed to ${verb}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteChannel() {
    if (!window.confirm(`Permanently delete #${team.name}? This removes its members, connection assignments, and AI history. This cannot be undone.`)) return;
    setBusy(true);
    try {
      await api.delete(`/teams/${team.id}`);
      await refresh();
      navigate("/");
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Failed to delete");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
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
      <input
        value={category}
        onChange={(e) => setCategory(e.target.value)}
        placeholder="Category (e.g. Teams, Projects)"
        className="rounded-md border border-border bg-ground px-2.5 py-1.5 text-[12px] outline-none focus:border-accent"
      />

      <div className="font-mono text-[10px] uppercase tracking-wide text-ink-faint">Privacy</div>
      <select
        value={privacy}
        onChange={(e) => setPrivacy(e.target.value as ChannelPrivacy)}
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
          <button onClick={toggleArchive} disabled={busy} className="text-left text-[11.5px] text-ink-dim underline underline-offset-2 hover:text-watch">
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

function ActivityTab({ history }: { history: ChannelAIHistoryItem[] }) {
  if (history.length === 0) return <p className="text-[12px] text-ink-faint">No Channel AI activity yet.</p>;
  return (
    <div className="flex flex-col gap-2">
      {history.map((h) => (
        <div key={h.id} className="text-[11.5px]">
          <div className="flex justify-between text-[10px] text-ink-faint">
            <span>{h.user_name}</span>
            <span>{new Date(h.created_at).toLocaleDateString()}</span>
          </div>
          <div className="truncate text-ink-dim">{h.command}</div>
        </div>
      ))}
    </div>
  );
}
