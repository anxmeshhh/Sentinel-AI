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

  return (
    <>
      {/* The scope of everything below, plus the one reassurance that
          matters most - visible, but deliberately quiet. */}
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <ScopeBadge scope={scope} workspaceName={active?.name} />
        <span className="text-[11.5px] text-ink-faint">
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
      <ServiceCard icon={<ZoomIcon />} name="Zoom" status="Coming soon" desc="Meeting metadata — not yet available." connected={false} disabled to="/connections/zoom" />
      <ServiceCard icon={<SlackIcon />} name="Slack" status="Coming soon" desc="Gaps, unanswered questions, missing approvals — not yet available." connected={false} disabled to="/connections/slack" />
      <ServiceCard icon={<NotionIcon />} name="Notion" status="Coming soon" desc="Stale or missing docs — not yet available." connected={false} disabled to="/connections/notion" />
    </div>
    </>
  );
}
