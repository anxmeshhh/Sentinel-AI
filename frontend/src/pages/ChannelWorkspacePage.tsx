import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { ChannelPath, ChannelReadiness, Team } from "../api/types";
import { ChannelBreadcrumb } from "../components/ChannelBreadcrumb";
import { ChannelModuleNav, CHANNEL_MODULES } from "../components/ChannelModuleNav";
import type { ChannelModuleKey } from "../components/ChannelModuleNav";
import { ChannelSetupChecklist } from "../components/ChannelSetupChecklist";
import { AttentionModule } from "../components/channel/AttentionModule";
import { ExtensionsModule } from "../components/channel/ExtensionsModule";
import { FeedModule } from "../components/channel/FeedModule";
import { InsightsModule } from "../components/channel/InsightsModule";
import { KnowledgeModule } from "../components/channel/KnowledgeModule";
import { PrepareModule } from "../components/channel/PrepareModule";
import { MembersModule } from "../components/channel/MembersModule";
import { NotBuiltModule } from "../components/channel/NotBuiltModule";
import { SentinelModule } from "../components/channel/SentinelModule";
import { SettingsModule } from "../components/channel/SettingsModule";
import { Badge, LoadingBlock, PageHeader } from "../components/ui";

const DEFAULT_MODULE: ChannelModuleKey = "sentinel";

/**
 * The Channel shell: identity, breadcrumb, module switcher.
 *
 * It loads only what every module needs - the channel itself, the
 * breadcrumb, and the caller's own setup readiness. Each module fetches its
 * own data when it mounts, so opening a channel is one request per pane
 * rather than nine up front.
 */
export function ChannelWorkspacePage() {
  const { teamId = "", module } = useParams<{ teamId: string; module?: string }>();
  const [team, setTeam] = useState<Team | null>(null);
  const [path, setPath] = useState<ChannelPath | null>(null);
  const [readiness, setReadiness] = useState<ChannelReadiness | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const activeModule = (module as ChannelModuleKey) ?? DEFAULT_MODULE;
  const isAdmin = team?.my_channel_role === "channel_admin";
  const blockingCount = readiness?.blocking_providers.length ?? 0;

  const loadShell = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [t, p, r] = await Promise.all([
        api.get<Team>(`/teams/${teamId}`),
        api.get<ChannelPath>(`/teams/${teamId}/path`),
        api.get<ChannelReadiness>(`/teams/${teamId}/readiness`),
      ]);
      setTeam(t);
      setPath(p);
      setReadiness(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load this channel");
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    void loadShell();
  }, [loadShell]);

  // Live readiness: `syncing` is a temporary state that resolves server-side
  // when the first ingestion lands, but nothing used to tell the page - the
  // checklist sat on "Syncing" until a manual reload (a known Phase 2x-B
  // gap). Poll the one cheap endpoint only while something is actually
  // syncing; the moment nothing is, the interval stops existing.
  const anySyncing = readiness?.requirements.some((r) => r.state === "syncing") ?? false;
  useEffect(() => {
    if (!anySyncing) return;
    const interval = setInterval(() => {
      api.get<ChannelReadiness>(`/teams/${teamId}/readiness`).then(setReadiness).catch(() => undefined);
    }, 5000);
    return () => clearInterval(interval);
  }, [anySyncing, teamId]);

  if (loading) return <LoadingBlock />;
  if (error || !team) {
    return (
      <div className="max-w-lg rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
        <p className="text-lead text-crit">{error ?? "Channel not found."}</p>
        <Link to="/" className="mt-3 inline-block text-small underline underline-offset-2">
          Back to dashboard
        </Link>
      </div>
    );
  }

  const definition = CHANNEL_MODULES.find((m) => m.key === activeModule);

  return (
    <div className="w-full">
      {path && <ChannelBreadcrumb path={path} />}

      <PageHeader
        eyebrow={path?.workspace_name}
        title={`${team.icon ? `${team.icon} ` : "#"}${team.name}`}
        description={team.description || undefined}
        actions={
          <>
            {/* Privacy and role, as the same Badge every other status in the
                product uses. What a member may DO here is not guessable from
                the modules on screen, so the role is stated rather than
                discovered by clicking something that then refuses. */}
            {team.privacy !== "public" && (
              <Badge tone="outline">{team.privacy === "private" ? "Private" : "Invite only"}</Badge>
            )}
            <Badge tone={isAdmin ? "accent" : "neutral"}>
              {isAdmin ? "Channel admin" : "Member"}
            </Badge>
          </>
        }
      />

      {team.is_archived && (
        <div className="mb-4 rounded-md border border-watch/40 bg-watch/5 px-4 py-3 text-small text-watch">
          This channel is archived — Channel AI is disabled and it's hidden from the sidebar.
          {isAdmin && " Unarchive it from Settings to bring it back."}
        </div>
      )}

      <ChannelModuleNav teamId={teamId} isAdmin={isAdmin} blockingCount={blockingCount} />

      {/* Setup is a gate, not a module: if required integrations are
          missing, say so on every module rather than letting each one
          render an empty state that looks like "nothing happening". */}
      {readiness && blockingCount > 0 && activeModule !== "extensions" && (
        <div className="mb-4 rounded-md border border-watch/40 bg-watch/5 px-4 py-3 text-small">
          <span className="font-semibold text-watch">Setup incomplete.</span>{" "}
          <span className="text-ink-dim">
            You haven't connected {blockingCount} required integration{blockingCount === 1 ? "" : "s"} for this channel, so
            what you see here is incomplete.
          </span>{" "}
          <Link to={`/channels/${teamId}/extensions`} className="underline underline-offset-2 hover:text-ink">
            Finish setup
          </Link>
        </div>
      )}

      {/* A blocked member's own checklist leads the Extensions module: the
          thing they must act on comes before the admin-facing configuration
          (requirements, assigned connections, roster) underneath it. When
          they're already set up it drops to the bottom as a quiet
          confirmation instead. This is the "prominently guide incomplete
          users" the setup gateway is for. */}
      {activeModule === "extensions" && readiness && blockingCount > 0 && (
        <ChannelSetupChecklist readiness={readiness} teamId={teamId} workspaceId={team.workspace_id} />
      )}

      {definition && !definition.built ? (
        <NotBuiltModule label={definition.label} />
      ) : (
        <>
          {activeModule === "sentinel" && <SentinelModule teamId={teamId} channelName={team.name} isArchived={team.is_archived} className={path?.class_name} workspaceName={path?.workspace_name} />}
          {activeModule === "attention" && <AttentionModule teamId={teamId} />}
          {activeModule === "feed" && <FeedModule teamId={teamId} />}
          {activeModule === "prepare" && <PrepareModule teamId={teamId} />}
          {activeModule === "insights" && <InsightsModule teamId={teamId} />}
          {activeModule === "knowledge" && <KnowledgeModule teamId={teamId} />}
          {activeModule === "extensions" && (
            <ExtensionsModule
              teamId={teamId}
              workspaceId={team.workspace_id}
              isAdmin={isAdmin}
              readiness={readiness}
              onChanged={loadShell}
            />
          )}
          {activeModule === "members" && <MembersModule teamId={teamId} isAdmin={isAdmin} channelName={team.name} workspaceId={team.workspace_id} />}
          {activeModule === "settings" && isAdmin && <SettingsModule team={team} onChanged={loadShell} />}
        </>
      )}

      {/* When already set up, the checklist sits at the bottom as a quiet
          "you're connected" confirmation rather than leading the page. */}
      {activeModule === "extensions" && readiness && blockingCount === 0 && (
        <ChannelSetupChecklist readiness={readiness} teamId={teamId} workspaceId={team.workspace_id} />
      )}
    </div>
  );
}
