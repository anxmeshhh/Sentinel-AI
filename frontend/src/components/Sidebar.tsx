import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { useTeams } from "../context/TeamContext";
import { useWorkspace } from "../context/WorkspaceContext";
import type { Workspace } from "../context/WorkspaceContext";
import { CreateTeamModal } from "./CreateTeamModal";
import { CreateWorkspaceModal } from "./CreateWorkspaceModal";
import { InviteModal } from "./InviteModal";

// Operator-only surface (see IA.md - this isn't part of the customer IA).
const OPERATOR_NAV = [{ to: "/admin", label: "Admin & Observability" }];

type ModalState =
  | null
  | { type: "create-workspace" }
  | { type: "create-team" }
  | { type: "invite-workspace" }
  | { type: "invite-team"; teamId: string; teamName: string };

export function Sidebar() {
  const { workspaces, active, setActiveId, loading } = useWorkspace();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [modal, setModal] = useState<ModalState>(null);

  function handleLogout() {
    logout();
    navigate("/login");
  }

  const workspaceNav = [
    { to: "/", label: "Dashboard", end: true },
    ...(active?.kind === "personal" ? [{ to: "/assistant", label: "AI Assistant", end: false }] : []),
    { to: "/mail", label: "Mail", end: false },
    { to: "/calendar", label: "Calendar", end: false },
    { to: "/history", label: "History", end: false },
    { to: "/settings", label: "Agents", end: false },
  ];

  return (
    <>
      {/* Mobile top bar - only rendered below md, sidebar itself handles md+ */}
      <div className="sticky top-0 z-30 flex items-center gap-3 border-b border-border bg-surface px-4 py-3 md:hidden">
        <button
          onClick={() => setMobileOpen(true)}
          aria-label="Open menu"
          className="flex h-8 w-8 items-center justify-center border border-border"
        >
          <span className="sr-only">Menu</span>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M1 4h14M1 8h14M1 12h14" stroke="currentColor" strokeWidth="1.4" />
          </svg>
        </button>
        <Brand />
      </div>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 bg-black/70 md:hidden" onClick={() => setMobileOpen(false)} aria-hidden="true" />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex h-screen w-72 flex-none flex-col gap-7 overflow-y-auto border-r border-border bg-surface p-6 transition-transform duration-200 md:sticky md:top-0 md:z-auto md:w-64 md:translate-x-0 ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between">
          <Brand />
          <button
            onClick={() => setMobileOpen(false)}
            aria-label="Close menu"
            className="flex h-7 w-7 items-center justify-center md:hidden"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.4" />
            </svg>
          </button>
        </div>

        <WorkspaceSwitcher
          workspaces={workspaces}
          active={active}
          onChange={setActiveId}
          loading={loading}
          onCreateNew={() => setModal({ type: "create-workspace" })}
        />

        <nav className="flex flex-col gap-1">
          <div className="px-2.5 pb-2 text-[10.5px] uppercase tracking-[0.14em] text-ink-faint">Workspace</div>
          {workspaceNav.map((item) => (
            <NavItem key={item.to} to={item.to} end={item.end} label={item.label} onNavigate={() => setMobileOpen(false)} />
          ))}
        </nav>

        {active && active.kind !== "personal" && (
          <ChannelRail
            onCreateTeam={() => setModal({ type: "create-team" })}
            onInviteWorkspace={() => setModal({ type: "invite-workspace" })}
            onInviteTeam={(teamId, teamName) => setModal({ type: "invite-team", teamId, teamName })}
          />
        )}

        <nav className="flex flex-col gap-1">
          <div className="px-2.5 pb-2 text-[10.5px] uppercase tracking-[0.14em] text-ink-faint">Operator</div>
          {OPERATOR_NAV.map((item) => (
            <NavItem key={item.to} to={item.to} end={false} label={item.label} onNavigate={() => setMobileOpen(false)} />
          ))}
        </nav>

        <div className="mt-auto flex items-center gap-2.5 border-t border-border px-1 pt-4">
          <div className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-surface-2 text-[11px] font-semibold uppercase text-ink-dim">
            {user?.name?.[0] ?? "?"}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[12.5px] font-medium text-ink">{user?.name}</div>
            <div className="truncate text-[11px] text-ink-faint">{user?.email}</div>
          </div>
          <button
            onClick={handleLogout}
            aria-label="Log out"
            className="flex-none text-[11.5px] text-ink-faint underline underline-offset-2 hover:text-ink"
          >
            Log out
          </button>
        </div>
      </aside>

      {modal?.type === "create-workspace" && (
        <CreateWorkspaceModal onClose={() => setModal(null)} onCreated={(w) => setActiveId(w.id)} />
      )}
      {modal?.type === "create-team" && <CreateTeamModal onClose={() => setModal(null)} />}
      {modal?.type === "invite-workspace" && active && (
        <InviteModal scope={{ type: "workspace", id: active.id }} label={active.name} onClose={() => setModal(null)} />
      )}
      {modal?.type === "invite-team" && (
        <InviteModal scope={{ type: "team", id: modal.teamId }} label={`#${modal.teamName}`} onClose={() => setModal(null)} />
      )}
    </>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2 px-1">
      <div className="relative h-[22px] w-[22px] flex-none rounded-full border border-ink">
        <div className="absolute inset-[6px] rounded-full bg-ink" />
      </div>
      <span className="text-[14px] font-semibold tracking-tight">Sentinel</span>
    </div>
  );
}

function WorkspaceSwitcher({
  workspaces,
  active,
  onChange,
  loading,
  onCreateNew,
}: {
  workspaces: Workspace[];
  active: Workspace | null;
  onChange: (id: string) => void;
  loading: boolean;
  onCreateNew: () => void;
}) {
  if (loading) {
    return <div className="h-[52px] animate-pulse border border-border bg-surface-2" />;
  }
  return (
    <div className="flex flex-col gap-1 border border-border p-1">
      {workspaces.map((w) => {
        const isActive = w.id === active?.id;
        return (
          <button
            key={w.id}
            onClick={() => onChange(w.id)}
            className={`flex flex-col items-start px-3 py-2 text-left transition-colors ${
              isActive ? "bg-ink text-ground" : "hover:bg-surface-2"
            }`}
          >
            <span className={`text-[13px] font-semibold ${isActive ? "text-ground" : "text-ink-dim"}`}>{w.name}</span>
            <span className={`text-[10.5px] uppercase tracking-wide ${isActive ? "text-ground/60" : "text-ink-faint"}`}>
              {w.kind}
            </span>
          </button>
        );
      })}
      <button
        onClick={onCreateNew}
        className="flex items-center gap-2 px-3 py-2 text-left text-[12.5px] text-ink-faint hover:bg-surface-2 hover:text-ink"
      >
        <span className="text-[14px] leading-none">+</span> Create or join a workspace
      </button>
    </div>
  );
}

function ChannelRail({
  onCreateTeam,
  onInviteWorkspace,
  onInviteTeam,
}: {
  onCreateTeam: () => void;
  onInviteWorkspace: () => void;
  onInviteTeam: (teamId: string, teamName: string) => void;
}) {
  const { teams, loading, join, leave } = useTeams();

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between px-2.5 pb-2">
        <span className="text-[10.5px] uppercase tracking-[0.14em] text-ink-faint">Channels</span>
        <button onClick={onInviteWorkspace} className="text-[11px] text-ink-faint underline underline-offset-2 hover:text-ink">
          Invite
        </button>
      </div>

      {loading && <div className="h-8 animate-pulse bg-surface-2" />}

      {!loading &&
        teams.map((team) => (
          <div key={team.id} className="group flex items-center gap-1.5 px-2.5 py-1.5">
            <span className="text-ink-faint">#</span>
            <span className={`flex-1 truncate text-[13px] ${team.is_member ? "text-ink" : "text-ink-dim"}`}>{team.name}</span>
            <span className="text-[10.5px] text-ink-faint">{team.member_count}</span>
            {team.is_member ? (
              <button
                onClick={() => leave(team.id)}
                className="hidden text-[11px] text-ink-faint underline underline-offset-2 hover:text-crit group-hover:inline"
              >
                Leave
              </button>
            ) : (
              <button onClick={() => join(team.id)} className="text-[11px] font-medium text-ink-dim underline underline-offset-2 hover:text-ink">
                Join
              </button>
            )}
            <button
              onClick={() => onInviteTeam(team.id, team.name)}
              className="hidden text-[11px] text-ink-faint underline underline-offset-2 hover:text-ink group-hover:inline"
              aria-label={`Invite people to ${team.name}`}
            >
              Invite
            </button>
          </div>
        ))}

      <button
        onClick={onCreateTeam}
        className="flex items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px] text-ink-faint hover:text-ink"
      >
        <span className="text-[14px] leading-none">+</span> Create channel
      </button>
    </div>
  );
}

function NavItem({
  to,
  end,
  label,
  onNavigate,
}: {
  to: string;
  end: boolean;
  label: string;
  onNavigate: () => void;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      className={({ isActive }) =>
        `flex items-center gap-2.5 px-2.5 py-2 text-[13px] transition-colors ${
          isActive ? "font-semibold text-ink" : "text-ink-dim hover:text-ink"
        }`
      }
    >
      {({ isActive }) => (
        <>
          <span className={`h-1.5 w-1.5 flex-none rounded-full ${isActive ? "bg-ink" : "bg-ink-faint"}`} />
          {label}
        </>
      )}
    </NavLink>
  );
}
