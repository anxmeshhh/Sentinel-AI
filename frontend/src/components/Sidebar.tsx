import { NavLink } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Today's Brief", end: true },
  { to: "/history", label: "History", end: false },
  { to: "/settings", label: "Agents & Connections", end: false },
];

export function Sidebar() {
  return (
    <aside className="sticky top-0 flex h-screen w-56 flex-none flex-col gap-7 border-r border-border bg-surface p-5">
      <div className="flex items-center gap-2 px-1">
        <div className="relative h-[26px] w-[26px] flex-none rounded-full border-[1.5px] border-accent">
          <div className="absolute inset-[6px] rounded-full bg-accent" />
        </div>
        <span className="font-mono text-[13.5px] font-semibold tracking-wide">SENTINEL</span>
      </div>

      <nav className="flex flex-col gap-0.5">
        <div className="px-2.5 pb-1.5 font-mono text-[10.5px] uppercase tracking-[0.12em] text-ink-faint">
          Workspace
        </div>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] transition-colors ${
                isActive
                  ? "bg-accent/10 font-semibold text-ink"
                  : "text-ink-dim hover:bg-surface-2"
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={`h-1.5 w-1.5 flex-none rounded-full ${isActive ? "bg-accent" : "bg-ink-faint"}`}
                />
                {item.label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto px-1 font-mono text-[11.5px] text-ink-faint">
        Sentinel AI &middot; Phase 1
      </div>
    </aside>
  );
}
