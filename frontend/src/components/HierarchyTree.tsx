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
      <div className="flex-none border-b border-border px-4 py-5">
        <div className="truncate text-lead font-semibold text-ink" title={active.name}>
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

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-5">
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

/** The Personal portal's own navigation - deliberately a flat list.
 *
 * Personal has no classes or groups by design, and inventing an empty tree
 * here would imply structure that isn't allowed to exist. */
function PersonalNav() {
  const items = [
    { to: "/", label: "Dashboard", end: true },
    { to: "/attention", label: "Attention", end: false },
    { to: "/assistant", label: "AI Assistant", end: false },
    { to: "/mail", label: "Mail", end: false },
    { to: "/calendar", label: "Calendar", end: false },
    { to: "/drive", label: "Drive", end: false },
    { to: "/meet", label: "Meet", end: false },
    { to: "/history", label: "History", end: false },
  ];
  return (
    <>
      <div className="mb-1 px-2 text-body font-semibold text-ink">Personal</div>
      <p className="mb-3 px-2 text-caption leading-relaxed text-ink-faint">
        What matters to you, across your own connected accounts. Private to you.
      </p>
      <nav className="flex flex-col">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `rounded-sm px-2.5 py-2 text-small transition-colors ${
                isActive ? "bg-surface-2 font-semibold text-ink" : "text-ink-dim hover:bg-surface/60 hover:text-ink"
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </>
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
