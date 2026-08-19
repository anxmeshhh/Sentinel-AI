import { useEffect, useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { TreeClass, TreeGroup } from "../api/types";
import { useHierarchy } from "../context/HierarchyContext";
import { InviteModal } from "./InviteModal";
import { SharedConnectionsModal } from "./SharedConnectionsModal";
import { Icon } from "./ui";
import { ContextBadge } from "./ContextBar";
import { workspaceContext } from "./context";
import { useWorkspace } from "../context/WorkspaceContext";

const CLASS_ADMIN_ROLES = ["super_admin", "org_admin"];
const GROUP_ADMIN_ROLES = ["super_admin", "org_admin", "team_manager"];

/** The navigation pane: Classes -> Groups -> Channels, collapsible.
 *
 * This column navigates and nothing else. Creating a class or a group opens
 * a form scoped to that one level rather than editing in place, so the
 * sidebar never becomes a management surface for four different levels at
 * once.
 */
export function HierarchyTree() {
  const { active } = useWorkspace();
  const { tree, loading, refresh } = useHierarchy();
  const [creatingClass, setCreatingClass] = useState(false);
  const [inviting, setInviting] = useState(false);
  const [sharingWorkspace, setSharingWorkspace] = useState(false);

  if (!active) return null;

  if (active.kind === "personal") {
    return (
      <div className="px-3 py-4">
        <PersonalNav />
      </div>
    );
  }

  const canManageClasses = CLASS_ADMIN_ROLES.includes(active.role);

  return (
    <div className="flex h-full flex-col">
      <div className="flex-none border-b border-border px-3.5 py-4">
        <div className="truncate text-small font-semibold text-ink" title={active.name}>
          {active.name.trim()}
        </div>
        <div className="mt-1.5 flex items-center justify-between gap-2">
          {/* Replaces the raw workspace `kind` ("organization") with the
              context identity - icon, name and PRIVATE/SHARED - so the
              answer to "which world am I in" is stated, not inferred. */}
          <ContextBadge identity={workspaceContext(active)} />
          <div className="flex flex-none items-center gap-2.5">
            {canManageClasses && (
              <button
                onClick={() => setSharingWorkspace(true)}
                title="Connections shared with the whole workspace"
                className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
              >
                Shared
              </button>
            )}
            <button
              onClick={() => setInviting(true)}
              className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
            >
              Invite
            </button>
          </div>
        </div>
      </div>

      {inviting && (
        <InviteModal scope={{ type: "workspace", id: active.id }} label={active.name.trim()} onClose={() => setInviting(false)} />
      )}

      {sharingWorkspace && (
        <SharedConnectionsModal
          scope="workspace"
          workspaceId={active.id}
          label={active.name.trim()}
          onClose={() => setSharingWorkspace(false)}
        />
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-2.5 py-4">
        {loading && <div className="mx-2 h-6 animate-pulse rounded bg-surface-2" />}

        {!loading && tree.length === 0 && (
          <div className="px-2 py-4 text-small leading-relaxed text-ink-faint">
            No classes yet.
            {canManageClasses
              ? " Create one (e.g. Development) to start organizing teams and channels."
              : " An admin needs to create one before channels can exist here."}
          </div>
        )}

        {!loading && tree.map((klass) => <ClassNode key={klass.id} klass={klass} />)}

        {/* What Sentinel has actually changed here. Admin-only, because the
            trail spans everyone's actions - it answers "what did this system
            do in my workspace", which belongs to whoever is responsible for
            it. Routed but unreachable until now, which made it effectively
            not exist. */}
        {canManageClasses && (
          <NavLink
            to="/audit/actions"
            className={({ isActive }) =>
              `mt-2 rounded-sm px-2.5 py-2 text-small transition-colors ${
                isActive ? "bg-surface-2 font-semibold text-ink" : "text-ink-faint hover:bg-surface/60 hover:text-ink"
              }`
            }
          >
            Action history
          </NavLink>
        )}

        {canManageClasses && (
          <div className="mt-2 px-2">
            {creatingClass ? (
              <InlineCreate
                placeholder="Class name (e.g. Development)"
                onCancel={() => setCreatingClass(false)}
                onSubmit={async (name) => {
                  await api.post(`/workspaces/${active.id}/classes`, { name });
                  setCreatingClass(false);
                  await refresh();
                }}
              />
            ) : (
              <button
                onClick={() => setCreatingClass(true)}
                className="flex w-full items-center gap-1.5 py-1.5 text-left text-small text-ink-faint hover:text-ink"
              >
                <span className="text-lead leading-none">+</span> Create class
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ClassNode({ klass }: { klass: TreeClass }) {
  const { active } = useWorkspace();
  const { refresh } = useHierarchy();
  const [open, setOpen] = useState(true);
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [managingConnections, setManagingConnections] = useState(false);

  const canManageGroups = active != null && GROUP_ADMIN_ROLES.includes(active.role);
  const canManageClass = active != null && CLASS_ADMIN_ROLES.includes(active.role);

  return (
    <div className="group/class mb-1">
      <div className="flex items-center">
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-1 px-2 py-1 text-left text-caption font-semibold text-ink-faint hover:text-ink-dim"
        >
          <Chevron open={open} />
          <span className="truncate">
            {klass.icon ? `${klass.icon} ` : ""}
            {klass.name}
          </span>
        </button>
        {canManageClass && (
          <button
            onClick={() => setManagingConnections(true)}
            title="Shared connections for this class"
            className="mr-1 hidden flex-none px-1.5 text-micro text-ink-faint hover:text-brand group-hover/class:block"
          >
            connections
          </button>
        )}
      </div>
      {managingConnections && active && (
        <SharedConnectionsModal
          scope="class"
          workspaceId={active.id}
          classId={klass.id}
          label={klass.name}
          onClose={() => setManagingConnections(false)}
        />
      )}

      {open && (
        <div className="ml-2 border-l border-border pl-1.5">
          {klass.groups.length === 0 && (
            <div className="px-2 py-1 text-caption text-ink-faint">No groups yet</div>
          )}
          {klass.groups.map((group) => (
            <GroupNode key={group.id} group={group} classId={klass.id} />
          ))}

          {canManageGroups &&
            (creatingGroup ? (
              <div className="px-1 py-1">
                <InlineCreate
                  placeholder="Group name (e.g. Backend Team)"
                  onCancel={() => setCreatingGroup(false)}
                  onSubmit={async (name) => {
                    await api.post(`/workspaces/${active!.id}/classes/${klass.id}/groups`, { name });
                    setCreatingGroup(false);
                    await refresh();
                  }}
                />
              </div>
            ) : (
              <button
                onClick={() => setCreatingGroup(true)}
                className="px-2 py-1 text-left text-caption text-ink-faint hover:text-ink"
              >
                + Group
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

function GroupNode({ group, classId }: { group: TreeGroup; classId: string }) {
  const { active } = useWorkspace();
  const [managingConnections, setManagingConnections] = useState(false);
  const { refresh } = useHierarchy();
  const { teamId } = useParams<{ teamId: string }>();
  const navigate = useNavigate();
  const [open, setOpen] = useState(true);
  const [creatingChannel, setCreatingChannel] = useState(false);

  // A channel in this group is open - keep the group expanded so the user
  // never loses sight of where they are.
  const containsActive = group.channels.some((c) => c.id === teamId);
  useEffect(() => {
    if (containsActive) setOpen(true);
  }, [containsActive]);

  const canCreateChannel = active != null && GROUP_ADMIN_ROLES.includes(active.role);

  return (
    <div className="group/grp mb-0.5">
      <div className="flex items-center">
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-1.5 px-2 py-1.5 text-left text-small font-medium text-ink-dim transition-colors hover:text-ink"
        >
          <Chevron open={open} />
          <span className="truncate">
            {group.icon ? `${group.icon} ` : ""}
            {group.name}
          </span>
        </button>
        {canCreateChannel && (
          <button
            onClick={() => setManagingConnections(true)}
            title="Shared connections for this group"
            className="mr-1 hidden flex-none px-1.5 text-micro text-ink-faint hover:text-brand group-hover/grp:block"
          >
            connections
          </button>
        )}
      </div>
      {managingConnections && active && (
        <SharedConnectionsModal
          scope="group"
          workspaceId={active.id}
          classId={classId}
          groupId={group.id}
          label={group.name}
          onClose={() => setManagingConnections(false)}
        />
      )}

      {open && (
        <div className="ml-3">
          {group.channels.map((channel) => (
            <NavLink
              key={channel.id}
              to={`/channels/${channel.id}`}
              className={({ isActive }) =>
                `relative flex items-center gap-1.5 rounded-sm px-2.5 py-1.5 text-small transition-colors ${
                  isActive
                    ? "bg-surface-2 font-semibold text-ink before:absolute before:-left-1 before:top-1/2 before:h-4 before:w-[2.5px] before:-translate-y-1/2 before:rounded-full before:bg-brand"
                    : "text-ink-dim hover:bg-surface/60 hover:text-ink"
                }`
              }
            >
              <span className="text-ink-faint">{channel.icon || "#"}</span>
              <span className="min-w-0 flex-1 truncate">{channel.name}</span>
              {channel.privacy !== "public" && <Icon name="lock" size={12} className="text-ink-faint" />}
            </NavLink>
          ))}

          {group.channels.length === 0 && !creatingChannel && (
            <div className="px-2 py-1 text-caption text-ink-faint">No channels</div>
          )}

          {canCreateChannel &&
            (creatingChannel ? (
              <div className="px-1 py-1">
                <InlineCreate
                  placeholder="Channel name (e.g. api-development)"
                  onCancel={() => setCreatingChannel(false)}
                  onSubmit={async (name) => {
                    const created = await api.post<{ id: string }>(`/workspaces/${active!.id}/teams`, {
                      name,
                      group_id: group.id,
                    });
                    setCreatingChannel(false);
                    await refresh();
                    navigate(`/channels/${created.id}`);
                  }}
                />
              </div>
            ) : (
              <button
                onClick={() => setCreatingChannel(true)}
                className="px-2 py-1 text-left text-caption text-ink-faint hover:text-ink"
              >
                + Channel
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

/** Which providers exist, grouped as the user thinks of them: a provider
 *  family, its sub-surfaces, and the connection providers that switch it on.
 *
 *  This is the mental model the whole product rests on - Connections →
 *  Providers → Intelligence - made literal in the navigation. Adding Slack or
 *  Jira later is one entry here, and it appears in the sidebar automatically
 *  the moment a connection of that provider exists. Nothing is hardcoded to
 *  "always show" any more, so a provider you have not connected does not
 *  advertise surfaces that would be empty. */
const PROVIDER_FAMILIES: {
  label: string;
  connects: string[]; // any of these provider values means this family is present
  surfaces: { to: string; label: string }[];
}[] = [
  {
    label: "Google Workspace",
    connects: ["gmail", "google_calendar", "google_drive"],
    surfaces: [
      { to: "/mail", label: "Mail" },
      { to: "/calendar", label: "Calendar" },
      { to: "/drive", label: "Drive" },
      { to: "/meet", label: "Meet" },
    ],
  },
  {
    label: "GitHub",
    connects: ["github"],
    // GitHub's operational surface is its provider page; no separate
    // per-feature routes exist for it (yet), so the family header is the link.
    surfaces: [{ to: "/connections/github", label: "GitHub" }],
  },
  {
    label: "Slack",
    connects: ["slack"],
    surfaces: [{ to: "/connections/slack", label: "Slack" }],
  },
];

/** The Personal portal's navigation, in three tiers by purpose - Sentinel's
 *  own intelligence, then the connected providers feeding it, then utility.
 *
 *  Personal has no classes or groups by design, so this is a grouped list
 *  rather than a tree. What providers appear is driven by real connections,
 *  not a fixed roster: this is where "GitHub is connected but not navigable"
 *  is fixed, and where every future provider becomes reachable for free. */
function PersonalNav() {
  const [providers, setProviders] = useState<Set<string> | null>(null);

  useEffect(() => {
    api
      .get<{ provider: string }[]>("/connections")
      .then((rows) => setProviders(new Set(rows.map((r) => r.provider))))
      .catch(() => setProviders(new Set()));
  }, []);

  const connectedFamilies = PROVIDER_FAMILIES.filter(
    (f) => providers && f.connects.some((p) => providers.has(p)),
  );

  return (
    <>
      {/* Name and one word about visibility. The two-line paragraph that used
          to sit here ("What matters to you, across your own connected
          accounts. Private to you.") restated what the context dot and badge
          already say, and cost two lines at the top of every screen. */}
      <div className="mb-3 flex items-baseline gap-2 px-2">
        <span className="text-small font-semibold text-ink">Personal</span>
        <span className="text-micro text-ink-faint">Private to you</span>
      </div>

      {/* Tier 1 - Sentinel's own intelligence. Always present, because these
          are the product, not a provider.

          The Assistant sits first and carries the only coloured treatment in
          the sidebar, because it is the primary interface: everything below it
          is a way of looking at what the Assistant can already tell you. */}
      <nav className="mb-4 flex flex-col gap-0.5">
        <NavLink
          to="/assistant"
          className={({ isActive }) =>
            `flex items-center gap-2 rounded-md px-2.5 py-2 text-small font-medium transition-colors ${
              isActive
                ? "bg-accent/15 text-ink ring-1 ring-inset ring-accent/40"
                : "text-ink-dim hover:bg-accent/10 hover:text-ink"
            }`
          }
        >
          <span
            className="flex h-4 w-4 flex-none items-center justify-center rounded-full border border-accent/50"
            aria-hidden="true"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          </span>
          Assistant
        </NavLink>
        <PersonalNavLink to="/" label="Dashboard" end />
        <PersonalNavLink to="/attention" label="Attention" />
        <PersonalNavLink to="/situations" label="Situations" />
      </nav>

      {/* Tier 2 - the connected providers feeding Sentinel, grouped by family
          so the list stays legible as providers multiply. */}
      <div className="mb-1 px-2">
        <span className="label-sub text-ink-faint">Connections</span>
      </div>
      {providers === null ? (
        <div className="px-2.5 py-2 text-caption text-ink-faint">Loading…</div>
      ) : connectedFamilies.length === 0 ? (
        <NavLink to="/connections/google" className="block rounded-sm px-2.5 py-2 text-small text-ink-dim hover:bg-surface/60 hover:text-ink">
          Connect a service →
        </NavLink>
      ) : (
        <div className="mb-5 flex flex-col gap-3">
          {connectedFamilies.map((family) => (
            <div key={family.label}>
              {/* A single-surface family (GitHub today) needs no separate
                  header - its one link carries the name. A multi-surface one
                  (Google) gets a quiet typographic header, not a box. */}
              {family.surfaces.length > 1 && (
                <div className="mb-0.5 px-2.5 text-micro uppercase tracking-wide text-ink-faint">{family.label}</div>
              )}
              <nav className="flex flex-col">
                {family.surfaces.map((s) => (
                  <PersonalNavLink key={s.to} to={s.to} label={s.label} />
                ))}
              </nav>
            </div>
          ))}
          <NavLink to="/connections/google" className="px-2.5 py-1 text-caption text-ink-faint hover:text-ink">
            + Add a connection
          </NavLink>
        </div>
      )}

      {/* Tier 3 - utility. Separated so History (and later, more) does not sit
          at the same weight as the intelligence surfaces above. */}
      <nav className="flex flex-col border-t border-border pt-3">
        <PersonalNavLink to="/history" label="History" />
        <PersonalNavLink to="/settings" label="Settings" />
      </nav>
    </>
  );
}

function PersonalNavLink({ to, label, end = false }: { to: string; label: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `rounded-sm px-2.5 py-1.5 text-small transition-colors ${
          isActive ? "bg-surface-2 font-medium text-ink" : "text-ink-dim hover:bg-surface/60 hover:text-ink"
        }`
      }
    >
      {label}
    </NavLink>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <Icon
      name="chevronRight"
      size={13}
      className={`transition-transform duration-200 ${open ? "rotate-90" : ""}`}
    />
  );
}

function InlineCreate({
  placeholder,
  onSubmit,
  onCancel,
}: {
  placeholder: string;
  onSubmit: (name: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!value.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(value.trim());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to create");
      setBusy(false);
    }
  }

  return (
    <div>
      <input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void submit();
          if (e.key === "Escape") onCancel();
        }}
        onBlur={() => !value.trim() && onCancel()}
        placeholder={placeholder}
        disabled={busy}
        className="w-full rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
      />
      {error && <p className="mt-0.5 text-caption text-crit">{error}</p>}
    </div>
  );
}
