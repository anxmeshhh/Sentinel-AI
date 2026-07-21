import { NavLink } from "react-router-dom";

export type ChannelModuleKey =
  | "sentinel"
  | "attention"
  | "prepare"
  | "feed"
  | "insights"
  | "knowledge"
  | "extensions"
  | "members"
  | "settings";

export interface ChannelModuleDef {
  key: ChannelModuleKey;
  label: string;
  /** False when the backend for this module genuinely doesn't exist yet.
   *  Rendered as "not built" rather than as an empty working module - an
   *  empty Insights page and an unbuilt Insights page look identical to a
   *  user, and only one of them is honest. */
  built: boolean;
  adminOnly?: boolean;
}

export const CHANNEL_MODULES: ChannelModuleDef[] = [
  { key: "sentinel", label: "Sentinel", built: true },
  { key: "attention", label: "Attention", built: true },
  { key: "feed", label: "Feed", built: true },
  { key: "prepare", label: "Prepare Me", built: false },
  { key: "insights", label: "Insights", built: false },
  { key: "knowledge", label: "Knowledge", built: false },
  { key: "extensions", label: "Extensions", built: true },
  { key: "members", label: "Members", built: true },
  { key: "settings", label: "Settings", built: true, adminOnly: true },
];

/**
 * The channel's module switcher.
 *
 * Each entry is a route, not a tab over already-fetched state: only the
 * chosen module mounts, so opening a channel costs one request instead of
 * nine. `blockingCount` surfaces incomplete setup on the Extensions entry,
 * because that's the module that fixes it.
 */
export function ChannelModuleNav({
  teamId,
  isAdmin,
  blockingCount,
}: {
  teamId: string;
  isAdmin: boolean;
  blockingCount: number;
}) {
  return (
    <nav className="scroll-x mb-6 flex gap-1 border-b border-rule-strong pb-2.5 sm:flex-wrap">
      {CHANNEL_MODULES.filter((m) => !m.adminOnly || isAdmin).map((module) => (
        <NavLink
          key={module.key}
          to={`/channels/${teamId}/${module.key}`}
          className={({ isActive }) =>
            `flex flex-none items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 py-2 text-small transition-colors ${
              isActive
                ? "bg-surface-2 font-semibold text-ink shadow-card"
                : "text-ink-dim hover:bg-surface hover:text-ink"
            }`
          }
        >
          {module.label}
          {module.key === "extensions" && blockingCount > 0 && (
            <span
              title={`${blockingCount} required integration${blockingCount === 1 ? "" : "s"} still to connect`}
              className="rounded-full bg-watch/20 px-1.5 py-px text-micro font-bold text-watch"
            >
              {blockingCount}
            </span>
          )}
          {!module.built && <span className="text-micro text-ink-faint">soon</span>}
        </NavLink>
      ))}
    </nav>
  );
}
