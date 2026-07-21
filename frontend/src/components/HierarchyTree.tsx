import { useEffect, useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { TreeClass, TreeGroup } from "../api/types";
import { useHierarchy } from "../context/HierarchyContext";
import { InviteModal } from "./InviteModal";
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
      <div className="flex-none border-b border-border px-4 py-3">
        <div className="truncate text-[13.5px] font-semibold text-ink" title={active.name}>
          {active.name.trim()}
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[10.5px] uppercase tracking-wide text-ink-faint">{active.kind}</span>
          <button
            onClick={() => setInviting(true)}
            className="text-[11px] text-ink-faint underline underline-offset-2 hover:text-ink"
          >
            Invite
          </button>
        </div>
      </div>

      {inviting && (
        <InviteModal scope={{ type: "workspace", id: active.id }} label={active.name.trim()} onClose={() => setInviting(false)} />
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
        {loading && <div className="mx-2 h-6 animate-pulse rounded bg-surface-2" />}

        {!loading && tree.length === 0 && (
          <div className="px-2 py-4 text-[12px] leading-relaxed text-ink-faint">
            No classes yet.
            {canManageClasses
              ? " Create one (e.g. Development) to start organizing teams and channels."
              : " An admin needs to create one before channels can exist here."}
          </div>
        )}

        {!loading && tree.map((klass) => <ClassNode key={klass.id} klass={klass} />)}

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
                className="flex w-full items-center gap-1.5 py-1.5 text-left text-[12px] text-ink-faint hover:text-ink"
              >
                <span className="text-[14px] leading-none">+</span> Create class
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

  const canManageGroups = active != null && GROUP_ADMIN_ROLES.includes(active.role);

  return (
    <div className="mb-1">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-1 px-2 py-1 text-left text-[10.5px] font-semibold uppercase tracking-[0.12em] text-ink-faint hover:text-ink-dim"
      >
        <Chevron open={open} />
        <span className="truncate">
          {klass.icon ? `${klass.icon} ` : ""}
          {klass.name}
        </span>
      </button>

      {open && (
        <div className="ml-2 border-l border-border pl-1.5">
          {klass.groups.length === 0 && (
            <div className="px-2 py-1 text-[11.5px] text-ink-faint">No groups yet</div>
          )}
          {klass.groups.map((group) => (
            <GroupNode key={group.id} group={group} />
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
                className="px-2 py-1 text-left text-[11.5px] text-ink-faint hover:text-ink"
              >
                + Group
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

function GroupNode({ group }: { group: TreeGroup }) {
  const { active } = useWorkspace();
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
    <div className="mb-0.5">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-1 px-2 py-1 text-left text-[12px] font-medium text-ink-dim hover:text-ink"
      >
        <Chevron open={open} />
        <span className="truncate">
          {group.icon ? `${group.icon} ` : ""}
          {group.name}
        </span>
      </button>

      {open && (
        <div className="ml-3">
          {group.channels.map((channel) => (
            <NavLink
              key={channel.id}
              to={`/channels/${channel.id}`}
              className={({ isActive }) =>
                `flex items-center gap-1 rounded px-2 py-1 text-[12.5px] transition-colors ${
                  isActive ? "bg-surface-2 font-semibold text-ink" : "text-ink-dim hover:text-ink"
                }`
              }
            >
              <span className="text-ink-faint">{channel.icon || "#"}</span>
              <span className="min-w-0 flex-1 truncate">{channel.name}</span>
              {channel.privacy !== "public" && <span className="text-[9.5px] text-ink-faint">🔒</span>}
            </NavLink>
          ))}

          {group.channels.length === 0 && !creatingChannel && (
            <div className="px-2 py-1 text-[11px] text-ink-faint">No channels</div>
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
                className="px-2 py-1 text-left text-[11px] text-ink-faint hover:text-ink"
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
      <div className="mb-1 px-2 text-[13.5px] font-semibold text-ink">Personal</div>
      <p className="mb-3 px-2 text-[11px] leading-relaxed text-ink-faint">
        What matters to you, across your own connected accounts. Private to you.
      </p>
      <nav className="flex flex-col">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `rounded px-2 py-1.5 text-[12.5px] transition-colors ${
                isActive ? "bg-surface-2 font-semibold text-ink" : "text-ink-dim hover:text-ink"
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
    <svg
      width="9"
      height="9"
      viewBox="0 0 10 10"
      aria-hidden="true"
      className={`flex-none transition-transform ${open ? "rotate-90" : ""}`}
    >
      <path d="M3 1l5 4-5 4" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
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
        className="w-full rounded border border-border bg-ground px-2 py-1 text-[11.5px] outline-none focus:border-accent disabled:opacity-50"
      />
      {error && <p className="mt-0.5 text-[10.5px] text-crit">{error}</p>}
    </div>
  );
}
