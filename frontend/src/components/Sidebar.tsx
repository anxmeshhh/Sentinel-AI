import { useEffect, useRef, useState, type ReactElement } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useWorkspace } from "../context/WorkspaceContext";
import { HierarchyTree } from "./HierarchyTree";
import { GitHubIcon, GoogleIcon, MicrosoftIcon, NotionIcon, SlackIcon, ZoomIcon } from "./ProviderIcons";
import { Icon, type IconName, cn } from "./ui";

/**
 * The one sidebar.
 *
 * This replaces a 56px icon rail sitting beside a 248px tree - two columns for
 * one job, which is why the shell never read as a single application.
 * Everything the rail did still exists: the Sentinel mark moved to the top,
 * workspace switching and sign-out moved into the account menu at the bottom,
 * and Settings became an ordinary nav row instead of a mystery cog.
 *
 * The Assistant is the only row with a colour. It is the primary interface and
 * every other row is a way of looking at something the Assistant can already
 * tell you, so it gets the emphasis and nothing else competes for it.
 */
const PRIMARY: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/", label: "Dashboard", icon: "grid", end: true },
  { to: "/attention", label: "Attention", icon: "activity" },
  { to: "/situations", label: "Situations", icon: "layers" },
  // Findings is /attention filtered to origin="detected" - what Sentinel found,
  // as opposed to what you asked it to hold. There is no findings list
  // endpoint; see FindingsPage for why that is the honest implementation.
  { to: "/findings", label: "Findings", icon: "alert" },
  { to: "/memory", label: "Memory", icon: "brain" },
  { to: "/goals", label: "Goals", icon: "target" },
];

const UTILITY: { to: string; label: string; icon: IconName }[] = [
  { to: "/history", label: "Activity", icon: "clock" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

/** Provider families and the icon each shows. A family appears only when a
 *  connection of that provider actually exists - an unconnected service should
 *  never advertise a page that would be empty. */
const FAMILIES: {
  label: string;
  connects: string[];
  to: string;
  Glyph: () => ReactElement;
}[] = [
  {
    label: "Google Workspace",
    connects: ["gmail", "google_calendar", "google_drive"],
    to: "/connections/google",
    Glyph: GoogleIcon,
  },
  {
    label: "Microsoft 365",
    connects: [
      "microsoft_outlook_mail",
      "microsoft_outlook_calendar",
      "microsoft_todo",
      "microsoft_onedrive",
      "microsoft_onenote",
      "microsoft_teams",
    ],
    to: "/connections/microsoft",
    Glyph: MicrosoftIcon,
  },
  { label: "GitHub", connects: ["github"], to: "/connections/github", Glyph: GitHubIcon },
  { label: "Slack", connects: ["slack"], to: "/connections/slack", Glyph: SlackIcon },
  { label: "Zoom", connects: ["zoom"], to: "/zoom", Glyph: ZoomIcon },
  { label: "Notion", connects: ["notion"], to: "/connections/notion", Glyph: NotionIcon },
];

export function Sidebar({
  collapsed,
  onToggle,
  onOpenCreate,
}: {
  collapsed: boolean;
  onToggle: () => void;
  onOpenCreate: () => void;
}) {
  const { active } = useWorkspace();
  const [providers, setProviders] = useState<Set<string> | null>(null);

  // Connecting a service is a full-page redirect out to the provider and back,
  // which normally remounts this component fresh anyway - but a browser can
  // restore the page from cache on that return trip instead of truly
  // reloading it, so a plain refetch-on-mount can miss the connection that
  // was just made. Refetching on focus as well means the list is always
  // current by the time you look at it, without polling while you're away.
  useEffect(() => {
    let cancelled = false;
    function refetch() {
      api
        .get<{ provider: string }[]>("/connections")
        .then((rows) => !cancelled && setProviders(new Set(rows.map((r) => r.provider))))
        .catch(() => !cancelled && setProviders(new Set()));
    }
    refetch();
    window.addEventListener("focus", refetch);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", refetch);
    };
  }, [active?.id]);

  const connected = FAMILIES.filter((f) => providers && f.connects.some((p) => providers.has(p)));
  const isPersonal = active?.kind === "personal";

  return (
    <div className="flex h-full flex-col bg-surface">
      <div className="flex flex-none items-center justify-between gap-2 px-3 py-4">
        {!collapsed && (
          <div className="flex min-w-0 items-center gap-2">
            <span
              className="relative flex h-6 w-6 flex-none items-center justify-center rounded-lg bg-accent/15 ring-1 ring-inset ring-accent/40"
              aria-hidden="true"
            >
              <span className="h-2 w-2 rounded-full bg-accent" />
            </span>
            <span className="truncate text-small font-semibold tracking-tight text-ink">Sentinel</span>
          </div>
        )}
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="flex h-6 w-6 flex-none items-center justify-center rounded-md border border-border text-ink-faint transition-colors hover:border-border-strong hover:text-ink"
        >
          <Icon name={collapsed ? "chevronRight" : "chevronLeft"} size={13} />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {/* Which Sentinel these links lead to.
            Personal and group intelligence are the same engines run with a
            different Scope, so the nav under this label is identical either
            way - which is exactly why the label has to be here. Without it
            the only clue was the workspace name in the account footer, and
            "whose findings am I looking at" is not a question a person should
            have to answer by checking the bottom of the sidebar. */}
        {!collapsed && (
          <div className="mb-1.5 flex items-center gap-2 px-2.5">
            <Icon
              name={isPersonal ? "user" : "grid"}
              size={12}
              className="flex-none text-ink-faint"
            />
            <span
              className="truncate text-micro font-semibold uppercase tracking-wide text-ink-faint"
              title={isPersonal ? "Personal" : active?.name.trim()}
            >
              {isPersonal ? "Personal" : (active?.name.trim() || "Workspace")}
            </span>
          </div>
        )}

        <nav className="flex flex-col gap-0.5">
          <Row to="/assistant" label="Assistant" icon="sparkle" collapsed={collapsed} primary />
          {PRIMARY.map((r) => (
            <Row key={r.to} {...r} collapsed={collapsed} />
          ))}
        </nav>

        {/* Personal shows its connected services; an org workspace shows its
            Class -> Group -> Channel tree in the same slot. */}
        {isPersonal ? (
          <>
            {!collapsed && <SectionLabel>Connections</SectionLabel>}
            <nav className="mt-1 flex flex-col gap-0.5">
              {providers === null ? (
                !collapsed && <div className="px-2.5 py-2 text-caption text-ink-faint">Loading…</div>
              ) : connected.length === 0 ? (
                <Row to="/connections/google" label="Connect a service" icon="plus" collapsed={collapsed} />
              ) : (
                <>
                  {connected.map((f) => (
                    <NavLink
                      key={f.label}
                      to={f.to}
                      title={f.label}
                      className={({ isActive }) =>
                        cn(
                          "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-small transition-colors",
                          isActive
                            ? "bg-surface-2 font-medium text-ink"
                            : "text-ink-dim hover:bg-surface-2/60 hover:text-ink",
                        )
                      }
                    >
                      <span className="flex h-4 w-4 flex-none items-center justify-center">
                        <f.Glyph />
                      </span>
                      {!collapsed && <span className="truncate">{f.label}</span>}
                    </NavLink>
                  ))}
                  <Row to="/connections/google" label="Add connection" icon="plus" collapsed={collapsed} />
                </>
              )}
            </nav>
          </>
        ) : (
          !collapsed && <HierarchyTree />
        )}

        <nav className="mt-4 flex flex-col gap-0.5 border-t border-rule pt-3">
          {UTILITY.map((r) => (
            <Row key={r.to} {...r} collapsed={collapsed} />
          ))}
        </nav>
      </div>

      <AccountMenu collapsed={collapsed} onOpenCreate={onOpenCreate} />
    </div>
  );
}

function Row({
  to,
  label,
  icon,
  end,
  collapsed,
  primary,
}: {
  to: string;
  label: string;
  icon: IconName;
  end?: boolean;
  collapsed: boolean;
  primary?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      title={label}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-small transition-colors",
          primary
            ? isActive
              ? "bg-accent font-medium text-white"
              : "text-ink-dim hover:bg-accent/15 hover:text-ink"
            : isActive
              ? "bg-surface-2 font-medium text-ink"
              : "text-ink-dim hover:bg-surface-2/60 hover:text-ink",
        )
      }
    >
      <Icon name={icon} size={16} className="flex-none" />
      {!collapsed && <span className="truncate">{label}</span>}
    </NavLink>
  );
}

function SectionLabel({ children }: { children: string }) {
  return (
    <div className="mt-5 px-2.5 text-micro font-semibold uppercase tracking-wide text-ink-faint">
      {children}
    </div>
  );
}

/** Who you are, which workspace you are in, and the two things the old icon
 *  rail owned: switching workspace and signing out. */
function AccountMenu({ collapsed, onOpenCreate }: { collapsed: boolean; onOpenCreate: () => void }) {
  const { user, logout } = useAuth();
  const { workspaces, active, setActiveId } = useWorkspace();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const initial = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();

  return (
    <div ref={ref} className="relative flex-none border-t border-rule p-2">
      {open && (
        <div className="absolute bottom-full left-2 right-2 mb-1 overflow-hidden rounded-lg border border-border bg-surface-2 py-1 shadow-overlay">
          <p className="px-3 py-1.5 text-micro uppercase tracking-wide text-ink-faint">Workspaces</p>
          {workspaces.map((w) => (
            <button
              key={w.id}
              onClick={() => {
                setActiveId(w.id);
                setOpen(false);
                navigate("/");
              }}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-1.5 text-left text-caption transition-colors hover:bg-surface-3",
                w.id === active?.id ? "text-ink" : "text-ink-dim",
              )}
            >
              {w.id === active?.id ? (
                <Icon name="check" size={12} className="flex-none" />
              ) : (
                <span className="w-3 flex-none" />
              )}
              <span className="truncate">{w.name.trim()}</span>
            </button>
          ))}
          <button
            onClick={() => {
              onOpenCreate();
              setOpen(false);
            }}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-caption text-ink-dim transition-colors hover:bg-surface-3 hover:text-ink"
          >
            <Icon name="plus" size={12} className="flex-none" /> Create or join
          </button>
          <div className="my-1 border-t border-rule" />
          <button
            onClick={logout}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-caption text-ink-dim transition-colors hover:bg-surface-3 hover:text-crit"
          >
            <Icon name="logout" size={12} className="flex-none" /> Sign out
          </button>
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left transition-colors hover:bg-surface-2"
      >
        <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-accent/20 text-caption font-semibold text-accent-text">
          {initial}
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-caption font-medium text-ink">
                {user?.name || user?.email || "Account"}
              </span>
              <span className="block truncate text-micro text-ink-faint">
                {active?.name.trim() ?? "—"}
              </span>
            </span>
            <Icon name="chevronDown" size={13} className="flex-none text-ink-faint" />
          </>
        )}
      </button>
    </div>
  );
}
