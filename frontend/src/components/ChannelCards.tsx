import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { MyTeam } from "../api/types";
import { InviteModal } from "./InviteModal";

function formatRole(role: string): string {
  return role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ChannelCards({ onSelectWorkspace }: { onSelectWorkspace: (workspaceId: string) => void }) {
  const [teams, setTeams] = useState<MyTeam[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<MyTeam | null>(null);

  function load() {
    setLoading(true);
    api
      .get<MyTeam[]>("/teams/mine")
      .then(setTeams)
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return teams;
    return teams.filter((t) => t.name.toLowerCase().includes(q) || t.workspace_name.toLowerCase().includes(q));
  }, [teams, query]);

  function handleSelect(team: MyTeam) {
    onSelectWorkspace(team.workspace_id);
    setSelected(team);
  }

  async function handleLeave(team: MyTeam) {
    await api.post(`/teams/${team.id}/leave`);
    setSelected(null);
    load();
  }

  return (
    <section className="mb-8">
      <div className="mb-2.5 flex items-center justify-between gap-3">
        <div className="font-mono text-[13px] font-bold uppercase tracking-wide text-ink-dim">My Channels</div>
        {teams.length > 3 && (
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter channels…"
            className="w-40 rounded-md border border-border bg-surface px-2.5 py-1 text-[12px] outline-none focus:border-accent"
          />
        )}
      </div>

      {loading ? (
        <div className="text-[12.5px] text-ink-faint">Loading&hellip;</div>
      ) : teams.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-6 text-center text-[12.5px] text-ink-faint">
          You haven't joined any channels yet — join one from a group's channel rail in the sidebar.
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-6 text-center text-[12.5px] text-ink-faint">
          No channels match "{query}".
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((t) => (
            <button
              key={t.id}
              onClick={() => handleSelect(t)}
              className={`rounded-lg border p-4 text-left transition-colors ${
                selected?.id === t.id ? "border-accent bg-accent/5" : "border-border bg-surface hover:border-accent/50"
              }`}
            >
              <div className="mb-2 flex items-center gap-2">
                <span className="text-ink-faint">#</span>
                <span className="truncate text-[13.5px] font-semibold text-ink">{t.name}</span>
              </div>
              <div className="mb-2 truncate text-[11.5px] text-ink-faint">in {t.workspace_name}</div>
              <div className="flex items-center gap-3 text-[11px] text-ink-dim">
                <span>{t.member_count} member{t.member_count === 1 ? "" : "s"}</span>
                <span>&middot;</span>
                <span>{formatRole(t.role)}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <ChannelDetailPanel
          team={selected}
          onClose={() => setSelected(null)}
          onLeave={() => handleLeave(selected)}
        />
      )}
    </section>
  );
}

function ChannelDetailPanel({ team, onClose, onLeave }: { team: MyTeam; onClose: () => void; onLeave: () => void }) {
  const [inviteOpen, setInviteOpen] = useState(false);

  return (
    <div className="mt-3 rounded-md border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[14px] font-semibold text-ink">#{team.name}</div>
          <div className="text-[12px] text-ink-faint">in {team.workspace_name}</div>
        </div>
        <button onClick={onClose} aria-label="Close" className="flex-none text-ink-faint hover:text-ink">
          ✕
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-dim">
        <span>{team.member_count} member{team.member_count === 1 ? "" : "s"}</span>
        <span>Your role: {formatRole(team.role)}</span>
      </div>

      <div className="mt-4 flex gap-2.5">
        <button
          onClick={() => setInviteOpen(true)}
          className="rounded-md border border-border px-3 py-1.5 font-mono text-[11.5px] text-ink-dim hover:border-accent hover:text-ink"
        >
          Invite
        </button>
        <button onClick={onLeave} className="font-mono text-[11.5px] text-crit underline underline-offset-2">
          Leave channel
        </button>
      </div>

      {inviteOpen && (
        <InviteModal scope={{ type: "team", id: team.id }} label={`#${team.name}`} onClose={() => setInviteOpen(false)} />
      )}
    </div>
  );
}
