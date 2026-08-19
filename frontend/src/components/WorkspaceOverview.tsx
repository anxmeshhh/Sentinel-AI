import { useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Connection, MyTeam } from "../api/types";
import {
  GitHubIcon,
  GoogleIcon,
  MicrosoftIcon,
  NotionIcon,
  SlackIcon,
  ZoomIcon,
} from "./ProviderIcons";
import { useWorkspace } from "../context/WorkspaceContext";
import { Badge, Button, ButtonLink, Icon, Input, cn } from "./ui";

/**
 * Workspace Overview - channels and connections, below the intelligence.
 *
 * These used to BE the dashboard: My Groups and My Channels opened the page,
 * six cards each reading "1 member · Org Admin", with the whole intelligence
 * product compressed into a strip above them. That is an admin console wearing
 * a dashboard's name, which is why this now sits underneath - present, one
 * click from anything, no longer the first thing Sentinel says about itself.
 *
 * Same components and tokens as the Command Center above it, so the page reads
 * as one surface rather than a dashboard with an admin panel stapled on.
 *
 * Every value is real: channels come from /teams/mine and connection status is
 * derived from the /connections rows the rest of the page already loaded.
 */
export function WorkspaceOverview({ connections }: { connections: Connection[] }) {
  return (
    <section className="mt-10 border-t border-rule pt-8">
      <MyChannels />
      <Connections connections={connections} />
    </section>
  );
}

/* ------------------------------------------------------------ channels -- */

function MyChannels() {
  const { setActiveId } = useWorkspace();
  const [teams, setTeams] = useState<MyTeam[] | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api
      .get<MyTeam[]>("/teams/mine")
      .then(setTeams)
      .catch(() => setTeams([]));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = teams ?? [];
    if (!q) return rows;
    return rows.filter(
      (t) => t.name.toLowerCase().includes(q) || t.workspace_name.toLowerCase().includes(q),
    );
  }, [teams, query]);

  // A person with no channels does not need an empty grid explaining channels
  // to them - the section simply is not there.
  if (teams !== null && teams.length === 0) return null;

  return (
    <div className="mb-8">
      <SectionHead title="My channels" count={teams?.length}>
        {(teams?.length ?? 0) > 4 && (
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter channels…"
            className="h-8 w-[180px] text-caption"
          />
        )}
      </SectionHead>

      {teams === null ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-[76px] animate-pulse rounded-lg border border-border bg-surface" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <p className="text-caption text-ink-faint">No channel matches “{query}”.</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((t) => (
            <Link
              key={t.id}
              to={`/channels/${t.id}`}
              // Switching the active workspace keeps the channel and the rest
              // of the app in the same scope - the behaviour the old cards had.
              onClick={() => setActiveId(t.workspace_id)}
              className="group rounded-lg border border-border bg-surface p-3.5 transition-colors hover:border-border-strong hover:bg-surface-2/60"
            >
              <div className="flex items-center gap-2">
                <Icon name="hash" size={14} className="flex-none text-ink-faint" />
                <span className="truncate text-small font-medium text-ink">{t.name}</span>
              </div>
              <p className="mt-1 truncate text-micro text-ink-faint">{t.workspace_name}</p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <Badge tone="outline">
                  {t.member_count} member{t.member_count === 1 ? "" : "s"}
                </Badge>
                <Badge tone="outline">{formatRole(t.channel_role)}</Badge>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function formatRole(role: string): string {
  return role
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/* --------------------------------------------------------- connections -- */

interface ProviderTile {
  name: string;
  Glyph: () => ReactElement;
  services: string;
  to: string;
  /** Providers Sentinel has no connector for. Shown so the set reads as
   *  complete, but never as connectable - and never as "coming soon", which
   *  would be a roadmap promise rather than a fact. */
  unavailable?: boolean;
}

function Connections({ connections }: { connections: Connection[] }) {
  const google = connections.filter((c) => c.provider.startsWith("google") || c.provider === "gmail");
  const microsoft = connections.filter((c) => c.provider.startsWith("microsoft_"));
  const github = connections.filter((c) => c.provider === "github");
  const slack = connections.filter((c) => c.provider === "slack");
  const zoom = connections.filter((c) => c.provider === "zoom");

  const tiles: { tile: ProviderTile; rows: Connection[] }[] = [
    {
      tile: {
        name: "Google Workspace",
        Glyph: GoogleIcon,
        services: "Gmail, Calendar, Drive, Meet",
        to: "/connections/google",
      },
      rows: google,
    },
    {
      tile: {
        name: "Microsoft 365",
        Glyph: MicrosoftIcon,
        services: "Outlook, Calendar, To Do, OneDrive, OneNote",
        to: "/connections/microsoft",
      },
      rows: microsoft,
    },
    {
      tile: {
        name: "GitHub",
        Glyph: GitHubIcon,
        services: "PRs, commits, issues",
        to: "/connections/github",
      },
      rows: github,
    },
    {
      tile: { name: "Slack", Glyph: SlackIcon, services: "Channel activity", to: "/connections/slack" },
      rows: slack,
    },
    {
      tile: { name: "Zoom", Glyph: ZoomIcon, services: "Meetings, recordings", to: "/zoom" },
      rows: zoom,
    },
    {
      tile: {
        name: "Notion",
        Glyph: NotionIcon,
        services: "No connector yet",
        to: "",
        unavailable: true,
      },
      rows: [],
    },
    {
      tile: {
        name: "Jira",
        // No brand mark exists in ProviderIcons and inventing one would be a
        // worse lie than a neutral glyph for a provider Sentinel cannot reach.
        Glyph: () => <Icon name="layers" size={16} className="text-ink-faint" />,
        services: "No connector yet",
        to: "",
        unavailable: true,
      },
      rows: [],
    },
  ];

  return (
    <div>
      <SectionHead title="Connections">
        <Link to="/settings" className="text-caption text-ink-faint transition-colors hover:text-ink">
          What Sentinel watches →
        </Link>
      </SectionHead>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {tiles.map(({ tile, rows }) => (
          <ConnectionTile key={tile.name} tile={tile} rows={rows} />
        ))}
      </div>
    </div>
  );
}

function ConnectionTile({ tile, rows }: { tile: ProviderTile; rows: Connection[] }) {
  const unhealthy = rows.filter((c) => c.state === "error" || c.state === "token_revoked").length;
  const connected = rows.length > 0;

  const status: { label: string; tone: "good" | "crit" | "neutral" } = tile.unavailable
    ? { label: "Not available", tone: "neutral" }
    : !connected
      ? { label: "Not connected", tone: "neutral" }
      : unhealthy > 0
        ? { label: `${unhealthy} need${unhealthy === 1 ? "s" : ""} attention`, tone: "crit" }
        : {
            label: `${rows.length} service${rows.length === 1 ? "" : "s"} connected`,
            tone: "good",
          };

  return (
    <div
      className={cn(
        "flex flex-col rounded-lg border border-border bg-surface p-3.5",
        tile.unavailable && "opacity-55",
      )}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="flex h-5 w-5 flex-none items-center justify-center">
          <tile.Glyph />
        </span>
        <span className="truncate text-small font-medium text-ink">{tile.name}</span>
      </div>

      <div className="mt-2">
        <Badge tone={status.tone === "neutral" ? "outline" : status.tone}>{status.label}</Badge>
      </div>

      <p className="mt-1.5 line-clamp-1 text-micro text-ink-faint">{tile.services}</p>

      <div className="mt-3">
        {tile.unavailable ? (
          <Button size="sm" disabled>
            Connect
          </Button>
        ) : (
          <ButtonLink to={tile.to} size="sm" variant={connected ? "secondary" : "primary"}>
            {connected ? "Manage" : "Connect"}
          </ButtonLink>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- shared -- */

function SectionHead({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <h2 className="flex items-center gap-2 text-small font-semibold text-ink">
        {title}
        {count !== undefined && (
          <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-micro text-ink-dim">{count}</span>
        )}
      </h2>
      {children}
    </div>
  );
}
