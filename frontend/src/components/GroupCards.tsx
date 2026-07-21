import { useMemo, useState } from "react";

import type { Workspace } from "../context/WorkspaceContext";

function formatRole(role: string): string {
  return role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatKind(kind: string): string {
  return kind.charAt(0).toUpperCase() + kind.slice(1);
}

export function GroupCards({
  workspaces,
  activeId,
  onSelect,
}: {
  workspaces: Workspace[];
  activeId: string | null;
  onSelect: (id: string) => void;
}) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return workspaces;
    return workspaces.filter((w) => w.name.toLowerCase().includes(q));
  }, [workspaces, query]);

  return (
    <section className="mb-8">
      <div className="mb-2.5 flex items-center justify-between gap-3">
        <h2 className="text-title font-medium text-ink">My Groups</h2>
        {workspaces.length > 3 && (
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter groups…"
            className="w-40 rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
          />
        )}
      </div>

      {workspaces.length === 0 ? (
        <div className="border-y border-rule px-6 py-12 text-center text-small text-ink-faint">
          You're not in any groups yet.
        </div>
      ) : filtered.length === 0 ? (
        <div className="border-y border-rule px-6 py-12 text-center text-small text-ink-faint">
          No groups match "{query}".
        </div>
      ) : (
        <div className="card-grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((w) => (
            <button
              key={w.id}
              onClick={() => onSelect(w.id)}
              className={`card-interactive ${
                w.id === activeId ? "border-ink-faint bg-surface/60" : ""
              }`}
            >
              <div className="mb-3 flex items-center gap-2.5">
                <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md bg-surface-2 text-body font-bold text-ink-dim">
                  {w.name.slice(0, 1)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-body font-semibold text-ink">{w.name}</div>
                  <div className="text-caption text-ink-faint">{formatKind(w.kind)}</div>
                </div>
                {w.id === activeId && (
                  <span className="flex-none rounded-full border border-accent/40 px-2 py-[2px] text-micro text-accent-text">
                    ACTIVE
                  </span>
                )}
              </div>
              <div className="text-caption font-semibold text-ink-dim">{formatRole(w.role)}</div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
