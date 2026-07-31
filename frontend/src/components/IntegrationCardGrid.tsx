import type { Connection } from "../api/types";
import { useWorkspace } from "../context/WorkspaceContext";
import { GitHubIcon, GoogleIcon, NotionIcon, SlackIcon, ZoomIcon } from "./ProviderIcons";
import { ScopeBadge, scopeOf } from "./ScopeBadge";
import { ServiceCard } from "./ServiceCard";

// Dashboard-level summary only - each card navigates to its own dedicated
// Connection Workspace page (/connections/:provider), which is where
// individual services and (for Google) the AI Command interface live.
export function IntegrationCardGrid({ connections }: { connections: Connection[] }) {
  const { active } = useWorkspace();
  const scope = scopeOf(active);
  const githubConnections = connections.filter((c) => c.provider === "github");
  const googleCalendar = connections.find((c) => c.provider === "google_calendar");
  const gmail = connections.find((c) => c.provider === "gmail");
  const googleDrive = connections.find((c) => c.provider === "google_drive");
  const googleConnectedCount = [googleCalendar, gmail, googleDrive].filter(Boolean).length;

  // Slack, driven by real connection rows like GitHub - not a placeholder.
  // Connected = any Slack row exists (the workspace grant); channels are the
  // rows that point at a resource.
  const slackRows = connections.filter((c) => c.provider === "slack");
  const slackConnected = slackRows.length > 0;
  const slackChannels = slackRows.filter((c) => c.repo);
  const slackWorkspace = slackRows.find((c) => c.org)?.org;
  const slackLastSync = slackChannels
    .map((c) => c.last_synced_at)
    .filter((t): t is string => Boolean(t))
    .sort()
    .at(-1);

  return (
    <>
      {/* The scope of everything below, plus the one reassurance that
          matters most - visible, but deliberately quiet. */}
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <ScopeBadge scope={scope} workspaceName={active?.name} />
        <span className="text-caption text-ink-faint">
          {scope === "personal"
            ? "Personal connections stay private — Sentinel never shares them with a workspace or channel."
            : "Shared connections are available to this workspace's members through the channels you authorize."}
        </span>
      </div>

    <div className="mb-8 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <ServiceCard
        icon={<GoogleIcon />}
        name="Google"
        status={googleConnectedCount > 0 ? `${googleConnectedCount} service${googleConnectedCount === 1 ? "" : "s"} connected` : "Not connected"}
        desc="Gmail, Calendar, Meet, Drive — browse, ask, and get risk findings, or give the AI a command across all of them."
        connected={googleConnectedCount > 0}
        to="/connections/google"
      />
      <ServiceCard
        icon={<GitHubIcon />}
        name="GitHub"
        status={githubConnections.length > 0 ? `${githubConnections.length} repo${githubConnections.length === 1 ? "" : "s"} connected` : "Not connected"}
        desc="PRs, commits, issues, reviews — bottlenecks, hotspots, risky deploys."
        connected={githubConnections.length > 0}
        to="/connections/github"
      />
      <ServiceCard
        icon={<SlackIcon />}
        name="Slack"
        status={
          slackConnected
            ? slackChannels.length > 0
              ? `${slackChannels.length} channel${slackChannels.length === 1 ? "" : "s"} monitored`
              : "Connected — add a channel"
            : "Not connected"
        }
        desc={
          slackConnected
            ? `${slackWorkspace ?? "Workspace"} connected${
                slackLastSync
                  ? ` · synced ${new Date(slackLastSync).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
                  : ""
              }. Blockers, unanswered questions, incidents forming.`
            : "Blockers, unanswered questions, incidents forming across your channels."
        }
        connected={slackConnected}
        to="/connections/slack"
      />
      <ServiceCard icon={<ZoomIcon />} name="Zoom" status="Coming soon" desc="Meeting metadata — not yet available." connected={false} disabled to="/connections/zoom" />
      <ServiceCard icon={<NotionIcon />} name="Notion" status="Coming soon" desc="Stale or missing docs — not yet available." connected={false} disabled to="/connections/notion" />
    </div>
    </>
  );
}
