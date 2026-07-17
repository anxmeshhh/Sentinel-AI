import { NavLink } from "react-router-dom";

import { useWorkspace } from "../context/WorkspaceContext";

// Operator-only surface (see IA.md - this isn't part of the customer IA).
const OPERATOR_NAV = [{ to: "/admin", label: "Admin & Observability" }];

export function Sidebar() {
  const { workspaces, active, setActiveId, loading } = useWorkspace();

  const workspaceNav = [
    { to: "/", label: "Today's Brief", end: true },
    ...(active?.kind === "personal" ? [{ to: "/assistant", label: "AI Assistant", end: false }] : []),
    { to: "/history", label: "History", end: false },
    { to: "/settings", label: "Agents & Connections", end: false },
  ];

  return (
    <aside className="sticky top-0 flex h-screen w-60 flex-none flex-col gap-8 border-r border-border bg-surface p-6">
      <div className="flex items-center gap-2 px-1">
        <div className="relative h-[26px] w-[26px] flex-none rounded-full border-[1.5px] border-accent">
          <div className="absolute inset-[6px] rounded-full bg-accent" />
        </div>
        <span className="font-mono text-[13.5px] font-semibold tracking-wide">SENTINEL</span>
      </div>

      <WorkspaceSwitcher workspaces={workspaces} active={active} onChange={setActiveId} loading={loading} />

      <nav className="flex flex-col gap-1">
        <div className="px-2.5 pb-2 font-mono text-[10.5px] uppercase tracking-[0.14em] text-ink-faint">
          Workspace
        </div>
        {workspaceNav.map((item) => (
          <NavItem key={item.to} to={item.to} end={item.end} label={item.label} dotClass="bg-accent" />
        ))}
      </nav>

      <nav className="flex flex-col gap-1">
        <div className="px-2.5 pb-2 font-mono text-[10.5px] uppercase tracking-[0.14em] text-ink-faint">
          Operator
        </div>
        {OPERATOR_NAV.map((item) => (
          <NavItem key={item.to} to={item.to} end={false} label={item.label} dotClass="bg-watch" />
        ))}
      </nav>

      <div className="mt-auto px-1 font-mono text-[11.5px] text-ink-faint">Sentinel AI &middot; Phase 1.5</div>
    </aside>
  );
}

function WorkspaceSwitcher({
  workspaces,
  active,
  onChange,
  loading,
}: {
  workspaces: { id: string; name: string; kind: string }[];
  active: { id: string; name: string; kind: string } | null;
  onChange: (id: string) => void;
  loading: boolean;
}) {
  if (loading) {
    return <div className="h-[52px] animate-pulse rounded-lg border border-border bg-surface-2" />;
  }
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border p-1">
      {workspaces.map((w) => {
        const isActive = w.id === active?.id;
        return (
          <button
            key={w.id}
            onClick={() => onChange(w.id)}
            className={`flex flex-col items-start rounded-md px-3 py-2 text-left transition-colors ${
              isActive ? "bg-accent/10" : "hover:bg-surface-2"
            }`}
          >
            <span className={`text-[13px] font-semibold ${isActive ? "text-ink" : "text-ink-dim"}`}>{w.name}</span>
            <span className="font-mono text-[10.5px] uppercase tracking-wide text-ink-faint">{w.kind}</span>
          </button>
        );
      })}
    </div>
  );
}

function NavItem({ to, end, label, dotClass }: { to: string; end: boolean; label: string; dotClass: string }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] transition-colors ${
          isActive ? "bg-accent/10 font-semibold text-ink" : "text-ink-dim hover:bg-surface-2"
        }`
      }
    >
      {({ isActive }) => (
        <>
          <span className={`h-1.5 w-1.5 flex-none rounded-full ${isActive ? dotClass : "bg-ink-faint"}`} />
          {label}
        </>
      )}
    </NavLink>
  );
}
