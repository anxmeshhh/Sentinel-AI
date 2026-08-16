import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { useWorkspace } from "../context/WorkspaceContext";
import { Icon } from "./ui";
import { contextClasses, workspaceContext } from "./context";

/**
 * The context switcher: the narrow icon column on the far left.
 *
 * Its only job is answering "which world am I in?" - Personal portal, or one
 * of my organizations. Nothing inside a workspace appears here, because the
 * moment this column also held classes or channels it would stop being a
 * switcher and become a second navigation tree.
 *
 * Personal is pinned to the top and visually separated for the reason it
 * exists: "what matters to ME" and "what matters to this team" are different
 * questions, and mixing their entry points is how someone ends up unsure
 * whose data they're looking at.
 */
export function WorkspaceRail({ onOpenCreate }: { onOpenCreate: () => void }) {
  const { workspaces, active, setActiveId } = useWorkspace();
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const personal = workspaces.filter((w) => w.kind === "personal");
  const organizations = workspaces.filter((w) => w.kind !== "personal");

  function handleLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div className="flex h-full w-[68px] flex-none flex-col items-center gap-2.5 border-r border-border bg-ground py-4">
      <div className="relative mb-2 h-[26px] w-[26px] flex-none rounded-full border border-ink" title="Sentinel">
        <div className="absolute inset-[7px] rounded-full bg-ink" />
      </div>

      {personal.map((w) => (
        <RailButton
          key={w.id}
          label="Personal"
          glyph={<Icon name="user" size={17} />}
          isActive={w.id === active?.id}
          markerClass={contextClasses(workspaceContext(w)).solid}
          onClick={() => {
            setActiveId(w.id);
            navigate("/");
          }}
        />
      ))}

      {organizations.length > 0 && <div className="my-1.5 h-px w-7 bg-border" />}

      {organizations.map((w) => (
        <RailButton
          key={w.id}
          label={w.name}
          glyph={w.name.trim().slice(0, 2).toUpperCase()}
          isActive={w.id === active?.id}
          markerClass={contextClasses(workspaceContext(w)).solid}
          onClick={() => {
            setActiveId(w.id);
            navigate("/");
          }}
        />
      ))}

      <RailButton label="Create or join a workspace" glyph={<Icon name="plus" size={17} />} isActive={false} onClick={onOpenCreate} />

      <div className="mt-auto flex flex-col items-center gap-2">
        <RailButton label="Agents & settings" glyph={<Icon name="settings" size={17} />} isActive={false} onClick={() => navigate("/settings")} />
        <button
          onClick={handleLogout}
          title={`Log out (${user?.email ?? ""})`}
          aria-label="Log out"
          className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-small font-semibold text-ink-dim transition-colors hover:bg-surface-3 hover:text-ink"
        >
          {user?.name?.[0] ?? "?"}
        </button>
      </div>
    </div>
  );
}

function RailButton({
  label,
  glyph,
  isActive,
  onClick,
  markerClass = "bg-accent",
}: {
  label: string;
  glyph: ReactNode;
  isActive: boolean;
  onClick: () => void;
  /** The active marker inherits the workspace's context tone, so the rail
   *  answers "which world am I in" from peripheral vision alone. */
  markerClass?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-current={isActive ? "true" : undefined}
      className={`relative flex h-10 w-10 flex-none items-center justify-center rounded-md text-small font-semibold transition-colors ${
        isActive ? "bg-ink text-ground" : "bg-surface text-ink-dim hover:bg-surface-2 hover:text-ink"
      }`}
    >
      {/* Active marker on the rail edge, so the current context is readable
          without relying on fill colour alone. */}
      {isActive && <span className={`absolute -left-4 h-6 w-[3px] rounded-r-full ${markerClass}`} />}
      {glyph}
    </button>
  );
}
