import { Badge, Tabs, Tooltip } from "./ui";
import type { TabItem } from "./ui";

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
   *  Rendered as "soon" rather than as an empty working module - an empty
   *  Insights page and an unbuilt Insights page look identical to a user,
   *  and only one of them is honest. */
  built: boolean;
  adminOnly?: boolean;
}

export const CHANNEL_MODULES: ChannelModuleDef[] = [
  { key: "sentinel", label: "Sentinel", built: true },
  { key: "attention", label: "Attention", built: true },
  { key: "feed", label: "Feed", built: true },
  { key: "prepare", label: "Prepare Me", built: true },
  { key: "insights", label: "Insights", built: true },
  { key: "knowledge", label: "Knowledge", built: true },
  { key: "extensions", label: "Extensions", built: true },
  { key: "members", label: "Members", built: true },
  { key: "settings", label: "Settings", built: true, adminOnly: true },
];

/**
 * The channel's module switcher, built on the shared Tabs primitive.
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
  const items: TabItem[] = CHANNEL_MODULES.filter((m) => !m.adminOnly || isAdmin).map((module) => ({
    to: `/channels/${teamId}/${module.key}`,
    label: module.label,
    trailing:
      module.key === "extensions" && blockingCount > 0 ? (
        <Tooltip label={`${blockingCount} required integration${blockingCount === 1 ? "" : "s"} still to connect`}>
          <Badge tone="warn">{blockingCount}</Badge>
        </Tooltip>
      ) : !module.built ? (
        <span className="text-micro text-ink-faint">soon</span>
      ) : undefined,
  }));

  return <Tabs items={items} />;
}
