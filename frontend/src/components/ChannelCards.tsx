import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

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
        <div className="label-sub text-body font-bold text-ink-dim">My Channels</div>
        {teams.length > 3 && (
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter channels…"
            className="w-40 card px-2.5 py-1 text-small outline-none focus:border-accent"
          />
        )}
      </div>

      {loading ? (
        <div className="text-small text-ink-faint">Loading&hellip;</div>
      ) : teams.length === 0 ? (
        <div className="border-y border-rule px-6 py-12 text-center text-small text-ink-faint">
          You haven't joined any channels yet — join one from a group's channel rail in the sidebar.
        </div>
      ) : filtered.length === 0 ? (
        <div className="border-y border-rule px-6 py-12 text-center text-small text-ink-faint">
          No channels match "{query}".
        </div>
      ) : (
        <div className="card-grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((t) => (
            <button
              key={t.id}
              onClick={() => handleSelect(t)}
              className={`card-interactive ${
                selected?.id === t.id ? "border-ink-faint bg-surface/60" : ""
              }`}
            >
              <div className="mb-2 flex items-center gap-2">
                <span className="text-ink-faint">#</span>
                <span className="truncate text-body font-semibold text-ink">{t.name}</span>
              </div>
              <div className="mb-2 truncate text-caption text-ink-faint">in {t.workspace_name}</div>
              <div className="flex items-center gap-3 text-caption text-ink-dim">
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
    <div className="mt-3 card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-lead font-semibold text-ink">#{team.name}</div>
          <div className="text-small text-ink-faint">in {team.workspace_name}</div>
        </div>
        <button onClick={onClose} aria-label="Close" className="flex-none text-ink-faint hover:text-ink">
          ✕
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-small text-ink-dim">
        <span>{team.member_count} member{team.member_count === 1 ? "" : "s"}</span>
        <span>Your role: {formatRole(team.role)}</span>
      </div>

      <div className="mt-4 flex gap-2.5">
        <Link
          to={`/channels/${team.id}`}
          className="btn-primary"
        >
          Open channel &rarr;
        </Link>
        <button
          onClick={() => setInviteOpen(true)}
          className="rounded-md border border-border px-3 py-1.5 text-caption text-ink-dim hover:border-accent hover:text-ink"
        >
          Invite
        </button>
        <button onClick={onLeave} className="text-caption text-crit underline underline-offset-2">
          Leave channel
        </button>
      </div>

      {inviteOpen && (
        <InviteModal scope={{ type: "team", id: team.id }} label={`#${team.name}`} onClose={() => setInviteOpen(false)} />
      )}
    </div>
  );
}
