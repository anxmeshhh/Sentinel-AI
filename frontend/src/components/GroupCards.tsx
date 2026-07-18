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
        <div className="font-mono text-[13px] font-bold uppercase tracking-wide text-ink-dim">My Groups</div>
        {workspaces.length > 3 && (
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter groups…"
            className="w-40 rounded-md border border-border bg-surface px-2.5 py-1 text-[12px] outline-none focus:border-accent"
          />
        )}
      </div>

      {workspaces.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-6 text-center text-[12.5px] text-ink-faint">
          You're not in any groups yet.
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-6 text-center text-[12.5px] text-ink-faint">
          No groups match "{query}".
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((w) => (
            <button
              key={w.id}
              onClick={() => onSelect(w.id)}
              className={`rounded-lg border p-4 text-left transition-colors ${
                w.id === activeId ? "border-accent bg-accent/5" : "border-border bg-surface hover:border-accent/50"
              }`}
            >
              <div className="mb-3 flex items-center gap-2.5">
                <div className="flex h-9 w-9 flex-none items-center justify-center rounded-md bg-surface-2 text-[13px] font-bold uppercase text-ink-dim">
                  {w.name.slice(0, 1)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13.5px] font-semibold text-ink">{w.name}</div>
                  <div className="text-[11px] text-ink-faint">{formatKind(w.kind)}</div>
                </div>
                {w.id === activeId && (
                  <span className="flex-none rounded-full border border-accent/40 px-2 py-[2px] font-mono text-[9.5px] text-accent-text">
                    ACTIVE
                  </span>
                )}
              </div>
              <div className="text-[11.5px] font-semibold text-ink-dim">{formatRole(w.role)}</div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
