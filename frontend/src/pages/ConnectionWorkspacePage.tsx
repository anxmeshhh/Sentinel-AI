import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type {
  Connection,
  GitHubRepo,
  GitHubRepository,
  MicrosoftCapabilities,
  MicrosoftService,
  ProviderKey,
  ServiceIntelligence,
  SlackChannel,
  SlackChannelResource,
} from "../api/types";
import { BackNav } from "../components/BackNav";
import { ConnectScopeDialog } from "../components/ConnectScopeDialog";
import { RecentActivity } from "../components/RecentActivity";
import { ScopeNotice, scopeOf } from "../components/ScopeBadge";
import { SentinelPanel } from "../components/SentinelPanel";
import { SyncButton } from "../components/SyncButton";
import { workspaceContext } from "../components/context";
import { useWorkspace } from "../context/WorkspaceContext";
import { CalendarIcon, DriveIcon, GitHubIcon, GoogleIcon, MailIcon, MeetIcon, MicrosoftIcon, NotionIcon, SlackIcon, ZoomIcon } from "../components/ProviderIcons";
import { ServiceCard } from "../components/ServiceCard";
import { GITHUB_ASSISTANT, GOOGLE_ASSISTANT, MICROSOFT_ASSISTANT, type ProviderAssistantConfig } from "../components/workspace/assistantConfigs";
import { Badge, Button, LoadingBlock, TabBar, type TabBarItem } from "../components/ui";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const PROVIDER_META: Record<string, { label: string; icon: ReactNode }> = {
  google: { label: "Google", icon: <GoogleIcon /> },
  microsoft: { label: "Microsoft 365", icon: <MicrosoftIcon /> },
  github: { label: "GitHub", icon: <GitHubIcon /> },
  zoom: { label: "Zoom", icon: <ZoomIcon /> },
  slack: { label: "Slack", icon: <SlackIcon /> },
  notion: { label: "Notion", icon: <NotionIcon /> },
};

/** The four families with a real, built workspace below (not
 *  ComingSoonWorkspace) - only these get the Overview/Services/Insights/
 *  Activity/Settings tab shell. A family with nothing real behind it keeps
 *  the plain "coming soon" page rather than tabs with nothing to show. */
const REAL_FAMILIES = new Set(["google", "microsoft", "github", "slack"]);

/** This family's own connections, by ProviderKey - for the header's
 *  aggregate status and the Settings tab's connection list. */
const FAMILY_PROVIDERS: Record<string, ProviderKey[]> = {
  google: ["gmail", "google_calendar", "google_drive"],
  microsoft: [
    "microsoft_outlook_mail", "microsoft_outlook_calendar", "microsoft_todo",
    "microsoft_onedrive", "microsoft_onenote", "microsoft_teams",
  ],
  github: ["github"],
  slack: ["slack"],
};

/** This family's /workspace/{service}/intelligence keys - workspace.py's own
 *  SERVICE_PROVIDERS vocabulary, which is deliberately not identical to
 *  ProviderKey, so mapped separately rather than assumed to match. */
const FAMILY_SERVICES: Record<string, string[]> = {
  google: ["gmail", "google_calendar", "google_drive"],
  microsoft: ["microsoft_mail", "microsoft_calendar", "microsoft_todo", "microsoft_onedrive", "microsoft_onenote"],
  github: ["github"],
  slack: ["slack"],
};

/** RecentActivity's `sources` filter for this family - real ACTION_META
 *  labels only. Slack has none yet (no Slack action type exists), so its
 *  Activity tab honestly shows nothing rather than everyone's history. */
const FAMILY_ACTIVITY_SOURCES: Record<string, string[]> = {
  google: ["Gmail", "Google Calendar"],
  microsoft: ["Outlook Mail", "Outlook Calendar", "Microsoft To Do", "OneDrive", "OneNote"],
  github: ["GitHub"],
  slack: [],
};

/** Only set for a family with a real, already-built scoped chat endpoint. */
const FAMILY_ASSISTANT: Record<string, ProviderAssistantConfig | undefined> = {
  google: GOOGLE_ASSISTANT,
  microsoft: MICROSOFT_ASSISTANT,
  github: GITHUB_ASSISTANT,
  slack: undefined,
};

/** Merges findings and de-duplicates situations across every service in a
 *  family - the same /workspace/{service}/intelligence each leaf page reads
 *  on its own, fetched once per service here and combined, since a family
 *  overview is "everything across Gmail, Calendar and Drive", not any one
 *  of them. A cross-provider situation surfacing under two services is
 *  de-duped by id rather than shown twice. */
function useFamilyIntelligence(services: string[]) {
  const [data, setData] = useState<{ findings: ServiceIntelligence["findings"]; situations: ServiceIntelligence["situations"] } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all(services.map((s) => api.get<ServiceIntelligence>(`/workspace/${s}/intelligence`).catch(() => null)))
      .then((results) => {
        if (cancelled) return;
        const findings = results.flatMap((r) => r?.findings ?? []);
        const situationsById = new Map<string, ServiceIntelligence["situations"][number]>();
        for (const r of results) for (const s of r?.situations ?? []) situationsById.set(s.id, s);
        setData({ findings, situations: [...situationsById.values()] });
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [services.join(",")]);

  return { data, loading };
}

type FamilyTabKey = "overview" | "services" | "insights" | "activity" | "settings";
const FAMILY_TABS: TabBarItem<FamilyTabKey>[] = [
  { key: "overview", label: "Overview" },
  { key: "services", label: "Services" },
  { key: "insights", label: "Insights" },
  { key: "activity", label: "Activity" },
  { key: "settings", label: "Settings" },
];

export function ConnectionWorkspacePage() {
  const { provider = "" } = useParams<{ provider: string }>();
  const { active } = useWorkspace();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<FamilyTabKey>("overview");

  function load() {
    setLoading(true);
    api
      .get<Connection[]>("/connections")
      .then(setConnections)
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  const meta = PROVIDER_META[provider];
  const isRealFamily = REAL_FAMILIES.has(provider);
  const familyProviders = FAMILY_PROVIDERS[provider] ?? [];
  const familyConnections = connections.filter((c) => familyProviders.includes(c.provider));
  const familyServices = FAMILY_SERVICES[provider] ?? [];
  const assistant = FAMILY_ASSISTANT[provider];
  const { data: familyIntel, loading: intelLoading } = useFamilyIntelligence(isRealFamily ? familyServices : []);

  const connectedCount = familyConnections.filter((c) => serviceHealth(c).healthy).length;
  const lastSyncedAt = familyConnections.reduce<string | null>(
    (max, c) => (c.last_synced_at && (!max || c.last_synced_at > max) ? c.last_synced_at : max),
    null,
  );

  return (
    <div>
      <BackNav back={{ to: "/", label: "Dashboard" }} crumbs={meta ? [{ label: "Dashboard", to: "/" }, { label: "Connections", to: "/" }, { label: meta.label }] : undefined} />

      {!meta ? (
        <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
          Unknown connection.
        </div>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-md bg-surface-2">{meta.icon}</div>
              <div>
                <h1 className="text-h2 font-medium text-balance">{meta.label}</h1>
                {isRealFamily && !loading && familyProviders.length > 0 && (
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-caption text-ink-faint">
                    <span className={`font-semibold ${connectedCount > 0 ? "text-good" : "text-ink-faint"}`}>
                      {connectedCount} of {familyProviders.length} services connected
                    </span>
                    {lastSyncedAt && (
                      <span>
                        · synced {new Date(lastSyncedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
            {isRealFamily && connectedCount > 0 && <SyncButton onSynced={load} />}
          </div>

          {/* Who can use anything connected here - stated up front, not
              hidden behind settings or a tooltip. */}
          <ScopeNotice scope={scopeOf(active)} workspaceName={active?.name} />

          {!isRealFamily ? (
            loading ? <LoadingBlock /> : <ComingSoonWorkspace label={meta.label} />
          ) : (
            <>
              <div className="mt-5">
                <TabBar items={FAMILY_TABS} value={tab} onChange={setTab} />
              </div>

              {tab === "overview" && (
                <div className="flex flex-col gap-6 xl:flex-row">
                  <div className="min-w-0 flex-1">
                    <FamilyIntelligenceCard data={familyIntel} loading={intelLoading} limit={3} onViewAll={() => setTab("insights")} />
                    <div className="mt-4">
                      <RecentActivity scope="personal" limit={5} sources={FAMILY_ACTIVITY_SOURCES[provider]} />
                    </div>
                  </div>
                  {assistant && (
                    <aside className="w-full flex-none xl:w-[360px]">
                      <div className="card h-[440px] overflow-hidden p-0 sm:p-0 xl:sticky xl:top-6">
                        <SentinelPanel
                          contextLabel={assistant.contextLabel}
                          identity={workspaceContext(active)}
                          endpointBase={assistant.endpointBase}
                          placeholder={assistant.placeholder}
                          suggestions={assistant.suggestions}
                          suggestionGroups={assistant.suggestionGroups}
                        />
                      </div>
                    </aside>
                  )}
                </div>
              )}

              {tab === "services" &&
                (loading ? (
                  <LoadingBlock />
                ) : provider === "google" ? (
                  <GoogleWorkspace connections={connections} onChanged={load} />
                ) : provider === "microsoft" ? (
                  <MicrosoftWorkspace connections={connections} onChanged={load} />
                ) : provider === "github" ? (
                  <GitHubWorkspace connections={connections} onChanged={load} />
                ) : (
                  <SlackWorkspace connections={connections} />
                ))}

              {tab === "insights" && <FamilyIntelligenceCard data={familyIntel} loading={intelLoading} />}

              {tab === "activity" && (
                <RecentActivity scope="personal" limit={20} sources={FAMILY_ACTIVITY_SOURCES[provider]} />
              )}

              {tab === "settings" && (
                <FamilySettingsTab label={meta.label} connections={familyConnections} onManage={() => setTab("services")} />
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

/** The family's merged findings/situations - same shape and rendering as
 *  ProviderWorkspace's own IntelligenceCard, so a leaf page and its family
 *  hub read identically. `limit` truncates for Overview; omitted, the
 *  Insights tab shows everything. */
function FamilyIntelligenceCard({
  data,
  loading,
  limit,
  onViewAll,
}: {
  data: { findings: ServiceIntelligence["findings"]; situations: ServiceIntelligence["situations"] } | null;
  loading: boolean;
  limit?: number;
  onViewAll?: () => void;
}) {
  if (loading && !data) return <LoadingBlock />;
  if (!data) return null;

  const findings = limit ? data.findings.slice(0, limit) : data.findings;
  const situations = limit ? data.situations.slice(0, limit) : data.situations;
  const quiet = data.findings.length === 0 && data.situations.length === 0;
  const more = limit && data.findings.length + data.situations.length > limit;

  return (
    <div className="card">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="relative h-[13px] w-[13px] flex-none rounded-full border border-ink" aria-hidden="true">
            <span className="absolute inset-[4px] rounded-full bg-brand" />
          </span>
          <span className="text-small font-semibold text-ink">Insights</span>
        </div>
        {more && onViewAll && (
          <button type="button" onClick={onViewAll} className="text-caption text-ink-faint hover:text-ink">
            View all →
          </button>
        )}
      </div>

      {quiet ? (
        <p className="text-caption leading-relaxed text-ink-faint">
          Nothing needs your attention across these services right now.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {situations.length > 0 && (
            <section>
              <div className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-ink-faint">Situations</div>
              <ul className="flex flex-col gap-2">
                {situations.map((s) => (
                  <li key={s.id} className="rounded-md border border-border px-3 py-2">
                    <div className="text-small font-medium text-ink">{s.title}</div>
                    {s.explanation && <p className="mt-1 text-caption leading-relaxed text-ink-dim">{s.explanation}</p>}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {findings.length > 0 && (
            <section>
              <div className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-ink-faint">Findings</div>
              <ul className="flex flex-col gap-2">
                {findings.map((f) => (
                  <li key={f.id} className="flex items-start gap-2">
                    <span
                      className={`mt-1.5 h-1.5 w-1.5 flex-none rounded-full ${
                        f.tier === "critical" ? "bg-crit" : f.tier === "review" ? "bg-warn" : "bg-ink-faint"
                      }`}
                      aria-hidden="true"
                    />
                    <div className="min-w-0">
                      <div className="truncate text-small text-ink">{f.title}</div>
                      <div className="truncate text-caption text-ink-faint">{f.why}</div>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

/** A read-only list of this family's connections - the real
 *  connect/reconnect/disconnect flow (OAuth, consent) stays on the Services
 *  tab, where it's already built; this tab just states what's connected. */
function FamilySettingsTab({
  label,
  connections,
  onManage,
}: {
  label: string;
  connections: Connection[];
  onManage: () => void;
}) {
  if (connections.length === 0) {
    return (
      <p className="text-caption text-ink-faint">
        Nothing connected yet.{" "}
        <button type="button" onClick={onManage} className="text-accent-text hover:underline">
          Connect a {label} service →
        </button>
      </p>
    );
  }
  return (
    <div className="card max-w-lg">
      <ul className="flex flex-col gap-3">
        {connections.map((c) => {
          const h = serviceHealth(c);
          return (
            <li key={c.id} className="flex items-center justify-between gap-3 border-b border-rule pb-3 last:border-0 last:pb-0">
              <div className="min-w-0">
                <div className="truncate text-small text-ink">{c.org || c.provider}</div>
                <div className="text-caption text-ink-faint">
                  {c.last_synced_at ? `Synced ${new Date(c.last_synced_at).toLocaleString()}` : "Never synced"}
                </div>
              </div>
              <Badge tone={h.tone === "muted" ? "neutral" : h.tone}>{h.status}</Badge>
            </li>
          );
        })}
      </ul>
      <button type="button" onClick={onManage} className="mt-4 text-caption text-accent-text hover:underline">
        Manage connections →
      </button>
    </div>
  );
}

type Health = { status: string; tone: "good" | "warn" | "crit" | "muted"; healthy: boolean };

/** Map a connection's real backend state to a card status - never "Connected"
 *  for a revoked or failing connection. */
function serviceHealth(conn: Connection | undefined): Health {
  if (!conn) return { status: "Not connected", tone: "muted", healthy: false };
  switch (conn.state) {
    case "ready":
      return { status: "Connected", tone: "good", healthy: true };
    case "live":
      return { status: "Live connected", tone: "good", healthy: true };
    case "syncing":
      return { status: "Syncing…", tone: "muted", healthy: true };
    case "error":
      return { status: "Sync failing", tone: "crit", healthy: false };
    case "token_revoked":
      return { status: "Reconnect needed", tone: "crit", healthy: false };
    case "paused":
      return { status: "Paused", tone: "muted", healthy: true };
    case "needs_setup":
      return { status: "Not set up", tone: "warn", healthy: false };
    default:
      return { status: "Connected", tone: "good", healthy: true };
  }
}

/** Meet has no connection of its own - it rides on Calendar, so its state IS
 *  Calendar's. Available when Calendar is healthy; unavailable if Calendar is
 *  broken; framed as availability rather than "connected". */
function meetHealth(calendar: Connection | undefined): Health {
  if (!calendar) return { status: "Not connected", tone: "muted", healthy: false };
  const cal = serviceHealth(calendar);
  if (cal.healthy) return { status: "Available", tone: "good", healthy: true };
  return { status: "Unavailable — Calendar issue", tone: "crit", healthy: false };
}

// Microsoft 365 - a workspace provider exactly like Google: one grant, child
// services. Sprint 1 exposes Outlook Mail and Outlook Calendar; the same page
// grows as later sprints add Teams/OneDrive/etc. The connect flow is identical
// to Google's, only the endpoint prefix differs.
function MicrosoftWorkspace({ connections, onChanged }: { connections: Connection[]; onChanged: () => void }) {
  const [connecting, setConnecting] = useState(false);
  const [caps, setCaps] = useState<MicrosoftCapabilities | null>(null);
  const [capsLoading, setCapsLoading] = useState(true);

  const microsoftRows = connections.filter((c) => c.provider.startsWith("microsoft_"));
  const teamsChannels = connections.filter((c) => c.provider === "microsoft_teams" && c.repo);
  const connectedCount = microsoftRows.length;

  // Capabilities are asked of Microsoft, so they refresh whenever the set of
  // connections changes - which is exactly when a different account has been
  // connected. No hardcoded assumption about what this account includes.
  useEffect(() => {
    let cancelled = false;
    setCapsLoading(true);
    api
      .get<MicrosoftCapabilities>("/integrations/microsoft/capabilities")
      .then((c) => !cancelled && setCaps(c))
      .catch(() => !cancelled && setCaps(null))
      .finally(() => !cancelled && setCapsLoading(false));
    return () => {
      cancelled = true;
    };
  }, [connections.length, microsoftRows.map((c) => c.org).join(",")]);

  async function handleConnect() {
    setConnecting(true);
    try {
      const { ticket } = await api.post<{ ticket: string }>("/integrations/microsoft/connect-ticket");
      window.location.href = `${API_BASE}/integrations/microsoft/connect?ticket=${encodeURIComponent(ticket)}`;
    } catch {
      setConnecting(false);
    }
  }

  async function handleDisconnectAll() {
    await Promise.all(microsoftRows.map((c) => api.delete(`/connections/${c.id}`)));
    onChanged();
  }

  const ICONS: Record<string, ReactNode> = {
    outlook_mail: <MailIcon />,
    outlook_calendar: <CalendarIcon />,
    teams: <MicrosoftIcon />,
    onedrive: <DriveIcon />,
    sharepoint: <DriveIcon />,
    onenote: <MailIcon />,
    planner: <CalendarIcon />,
    todo: <CalendarIcon />,
  };

  /** What one service card should say. An unavailable service is a capability
   *  statement, never an error - it explains what it needs and how to get it. */
  function cardFor(svc: MicrosoftService) {
    if (!svc.available) {
      return { status: `🔒 ${svc.status}`, tone: "muted" as const, connected: false, desc: svc.reason ?? svc.description };
    }
    if (svc.key === "teams" && teamsChannels.length > 0) {
      return {
        status: `${teamsChannels.length} channel${teamsChannels.length === 1 ? "" : "s"} monitored`,
        tone: "good" as const, connected: true, desc: svc.description,
      };
    }
    if (svc.connected) {
      const row = connections.find(
        (c) =>
          (svc.key === "outlook_mail" && c.provider === "microsoft_outlook_mail") ||
          (svc.key === "outlook_calendar" && c.provider === "microsoft_outlook_calendar"),
      );
      const health = row ? serviceHealth(row) : null;
      return {
        status: health?.status ?? "Connected",
        tone: health?.tone ?? ("good" as const),
        connected: health?.healthy ?? true,
        desc: svc.description,
      };
    }
    // Available to this account, but Sentinel isn't reading it yet. Not an
    // error either - it is the next thing the user could turn on.
    return { status: "Available — not set up yet", tone: "muted" as const, connected: false, desc: svc.description };
  }

  const available = caps?.services.filter((s) => s.available) ?? [];
  const locked = caps?.services.filter((s) => !s.available) ?? [];

  return (
    <div>
      {/* What kind of account this is, stated plainly - it is the reason some
          services below are unavailable, so it belongs above them. */}
      {caps?.connected && (
        <div className="mb-4 rounded-md border border-border bg-surface/50 px-4 py-3">
          <div className="text-small font-semibold text-ink">{caps.account_type_label}</div>
          <div className="mt-0.5 text-caption text-ink-faint">
            {caps.account}
            {caps.tenant_name ? ` · ${caps.tenant_name}` : ""}
            {locked.length > 0
              ? ` · ${available.length} of ${caps.services.length} services available on this account type`
              : ` · all ${caps.services.length} services available`}
          </div>
        </div>
      )}

      {capsLoading && !caps ? (
        <LoadingBlock />
      ) : (
        <>
          <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {available.map((svc) => {
              const c = cardFor(svc);
              return (
                <ServiceCard
                  key={svc.key}
                  icon={ICONS[svc.key] ?? <MicrosoftIcon />}
                  name={svc.label}
                  status={c.status}
                  statusTone={c.tone}
                  desc={c.desc}
                  connected={c.connected}
                  to={
                    c.connected && svc.key === "outlook_mail"
                      ? "/microsoft/mail"
                      : c.connected && svc.key === "outlook_calendar"
                        ? "/microsoft/calendar"
                        : c.connected && svc.key === "todo"
                          ? "/microsoft/todo"
                          : c.connected && svc.key === "onedrive"
                            ? "/microsoft/onedrive"
                            : c.connected && svc.key === "onenote"
                              ? "/microsoft/onenote"
                              : undefined
                  }
                />
              );
            })}
          </div>

          {/* Unavailable services are still shown - the point is to teach what
              exists and what it needs, not to hide it or call it an error. */}
          {locked.length > 0 && (
            <div className="mb-6">
              <div className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-faint">
                Available on work or school accounts
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {locked.map((svc) => {
                  const c = cardFor(svc);
                  return (
                    <ServiceCard
                      key={svc.key}
                      icon={ICONS[svc.key] ?? <MicrosoftIcon />}
                      name={svc.label}
                      status={c.status}
                      statusTone={c.tone}
                      desc={c.desc}
                      connected={false}
                    />
                  );
                })}
              </div>
              {locked[0]?.unlock && (
                <p className="mt-3 text-caption text-ink-faint">{locked[0].unlock}</p>
              )}
            </div>
          )}
        </>
      )}

      <div className="mb-2 flex flex-wrap items-center gap-3">
        <Button size="sm" variant="primary" onClick={handleConnect} disabled={connecting}>
          {connecting ? "Redirecting…" : connectedCount > 0 ? "Reconnect Microsoft 365" : "Connect Microsoft 365"}
        </Button>
        {connectedCount > 0 && (
          <Button size="sm" variant="danger" onClick={handleDisconnectAll}>
            Disconnect all
          </Button>
        )}
      </div>
    </div>
  );
}

function GoogleWorkspace({ connections, onChanged }: { connections: Connection[]; onChanged: () => void }) {
  const { active } = useWorkspace();
  const [connecting, setConnecting] = useState(false);
  // The disclosure gates the OAuth redirect - the user sees the destination
  // in Sentinel's words before leaving for Google's consent screen.
  const [showScopeDialog, setShowScopeDialog] = useState(false);
  const gmail = connections.find((c) => c.provider === "gmail");
  const googleCalendar = connections.find((c) => c.provider === "google_calendar");
  const googleDrive = connections.find((c) => c.provider === "google_drive");
  const connectedCount = [gmail, googleCalendar, googleDrive].filter(Boolean).length;

  async function handleConnect() {
    setConnecting(true);
    try {
      const { ticket } = await api.post<{ ticket: string }>("/integrations/google/connect-ticket");
      window.location.href = `${API_BASE}/integrations/google/connect?ticket=${encodeURIComponent(ticket)}`;
    } catch {
      setConnecting(false);
    }
  }

  async function handleDisconnect(id: string) {
    await api.delete(`/connections/${id}`);
    onChanged();
  }

  async function handleDisconnectAll() {
    const ids = [gmail?.id, googleCalendar?.id, googleDrive?.id].filter((id): id is string => Boolean(id));
    await Promise.all(ids.map((id) => api.delete(`/connections/${id}`)));
    onChanged();
  }

  const gmailH = serviceHealth(gmail);
  const calH = serviceHealth(googleCalendar);
  const driveH = serviceHealth(googleDrive);
  const meetH = meetHealth(googleCalendar);

  return (
    <div>
      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <ServiceCard
          icon={<MailIcon />}
          name="Gmail"
          status={gmailH.status}
          statusTone={gmailH.tone}
          desc={gmail?.org ?? "Subject, participants, timestamps — never message bodies"}
          connected={gmailH.healthy}
          to={gmail ? "/mail" : undefined}
          disabled={!gmail}
        />
        <ServiceCard
          icon={<CalendarIcon />}
          name="Google Calendar"
          status={calH.status}
          statusTone={calH.tone}
          desc={googleCalendar?.org ?? "Meetings, attendees, duration"}
          connected={calH.healthy}
          to={googleCalendar ? "/calendar" : undefined}
          disabled={!googleCalendar}
        />
        <ServiceCard
          icon={<MeetIcon />}
          name="Google Meet"
          status={meetH.status}
          statusTone={meetH.tone}
          desc="Rides on Calendar — no separate connection"
          connected={meetH.healthy}
          to={googleCalendar ? "/meet" : undefined}
          disabled={!googleCalendar}
        />
        <ServiceCard
          icon={<DriveIcon />}
          name="Google Drive"
          status={driveH.status}
          statusTone={driveH.tone}
          desc={googleDrive?.org ?? "File name, type, modified time — never file content"}
          connected={driveH.healthy}
          to={googleDrive ? "/drive" : undefined}
          disabled={!googleDrive}
        />
      </div>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <Button size="sm" variant="primary" onClick={() => setShowScopeDialog(true)} disabled={connecting}>
          {connecting ? "Redirecting…" : connectedCount > 0 ? "Reconnect Google" : "Connect Google"}
        </Button>
        {gmail && (
          <Button size="sm" variant="danger" onClick={() => handleDisconnect(gmail.id)}>
            Disconnect Gmail
          </Button>
        )}
        {googleCalendar && (
          <Button size="sm" variant="danger" onClick={() => handleDisconnect(googleCalendar.id)}>
            Disconnect Calendar
          </Button>
        )}
        {googleDrive && (
          <Button size="sm" variant="danger" onClick={() => handleDisconnect(googleDrive.id)}>
            Disconnect Drive
          </Button>
        )}
        {connectedCount > 0 && (
          <Button size="sm" variant="danger" onClick={handleDisconnectAll}>
            Disconnect all
          </Button>
        )}
      </div>

      {googleDrive === undefined && (gmail || googleCalendar) && (
        <p className="mb-4 text-small text-watch">
          Drive needs the newer Google connection scope — click "Reconnect Google" above to add it.
        </p>
      )}

      {showScopeDialog && (
        <ConnectScopeDialog
          providerName="Google"
          scope={scopeOf(active)}
          workspaceName={active?.name}
          services={[
            "Gmail — subjects, senders and dates (message bodies are only read when you ask)",
            "Calendar — events, times and attendees",
            "Drive — file names and types (contents only when you ask)",
          ]}
          busy={connecting}
          onCancel={() => setShowScopeDialog(false)}
          onConfirm={() => {
            setShowScopeDialog(false);
            void handleConnect();
          }}
        />
      )}
    </div>
  );
}

/**
 * GitHub, connected by OAuth.
 *
 * Replaces a personal-access-token form that had been failing since
 * connections became per-user: it never sent an owner, so every submission
 * hit a NOT NULL constraint. Nobody could have connected GitHub through it.
 *
 * The flow is two steps on purpose. One token can read many repositories and
 * Sentinel watches one, so authorizing does not by itself say which - and
 * picking for the user would quietly sync the wrong thing. The second step
 * offers exactly the repositories the granted scopes can actually read, so a
 * choice made here is known to work rather than typed and hoped for.
 */
const REPO_STATE: Record<string, { label: string; tone: string }> = {
  ready: { label: "Watching", tone: "text-good" },
  syncing: { label: "Syncing…", tone: "text-watch" },
  error: { label: "Sync failing", tone: "text-crit" },
  paused: { label: "Paused", tone: "text-ink-faint" },
  token_revoked: { label: "Reconnect needed", tone: "text-crit" },
  needs_setup: { label: "Not set up", tone: "text-watch" },
};

/**
 * GitHub as a multi-repository provider.
 *
 * One account, several watched repositories - each its own connection, so
 * each can be paused, synced or removed on its own. The page has two halves:
 * what Sentinel is watching (with per-repo health and controls), and the
 * repositories the account could add. When the account is not connected at
 * all, only the connect prompt shows.
 */
function GitHubWorkspace({ connections, onChanged }: { connections: Connection[]; onChanged: () => void }) {
  // The account is "connected" if any GitHub connection row exists - watched
  // or an anchor. connections here only carries watched repos (repo set), so
  // we probe the management endpoint to learn the true account state.
  const [watching, setWatching] = useState<GitHubRepository[]>([]);
  const [available, setAvailable] = useState<GitHubRepo[]>([]);
  const [accountConnected, setAccountConnected] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [adding, setAdding] = useState(false);

  const hasGitHub = connections.some((c) => c.provider === "github");

  const load = useCallback(async () => {
    try {
      const repos = await api.get<GitHubRepository[]>("/integrations/github/repositories");
      setWatching(repos);
      setAccountConnected(true);
    } catch (e) {
      // 404 means no GitHub account at all; anything else is a real error.
      if (e instanceof ApiError && e.status === 404) setAccountConnected(false);
      else setError(e instanceof ApiError ? e.message : "Couldn't load your repositories");
    }
  }, []);

  useEffect(() => {
    if (hasGitHub) void load();
    else setAccountConnected(false);
  }, [hasGitHub, load]);

  async function loadAvailable() {
    setAdding(true);
    setError(null);
    try {
      setAvailable(await api.get<GitHubRepo[]>("/integrations/github/repos"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load your repositories");
      setAdding(false);
    }
  }

  async function connect() {
    setBusy("connect");
    setError(null);
    try {
      const { ticket } = await api.post<{ ticket: string }>("/integrations/github/connect-ticket");
      const returnTo = encodeURIComponent("/connections/github");
      window.location.href = `${API_BASE}/integrations/github/connect?ticket=${encodeURIComponent(ticket)}&return_to=${returnTo}`;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start the GitHub connection");
      setBusy(null);
    }
  }

  async function addRepo(org: string, repo: string) {
    setBusy(`${org}/${repo}`);
    setError(null);
    try {
      await api.post("/integrations/github/repositories", { org, repo });
      setAdding(false);
      setFilter("");
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't add that repository");
    } finally {
      setBusy(null);
    }
  }

  async function setPriority(id: string, priority: string) {
    setBusy(id);
    setError(null);
    try {
      await api.patch(`/integrations/github/repositories/${id}/priority`, { priority });
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function repoAction(id: string, verb: "pause" | "resume" | "sync" | "remove") {
    setBusy(id);
    setError(null);
    try {
      if (verb === "remove") await api.delete(`/integrations/github/repositories/${id}`);
      else await api.post(`/integrations/github/repositories/${id}/${verb}`);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That didn't work");
    } finally {
      setBusy(null);
    }
  }

  const watchedKeys = new Set(watching.map((r) => r.full_name.toLowerCase()));
  const addable = available.filter(
    (r) => !watchedKeys.has(r.full_name.toLowerCase()) &&
      (!filter || r.full_name.toLowerCase().includes(filter.toLowerCase())),
  );

  if (accountConnected === null) return <LoadingBlock />;

  if (!accountConnected) {
    return (
      <div>
        {error && <p className="mb-3 text-small text-crit">{error}</p>}
        <div className="card p-4">
          <div className="mb-1 text-body font-semibold text-ink">Connect your GitHub account</div>
          <p className="mb-3 text-small leading-relaxed text-ink-dim">
            You'll authorize Sentinel on GitHub, then choose which repositories to watch. Sentinel reads pull request,
            commit, issue and review <span className="text-ink">metadata only</span> — never source code, diffs or file
            contents.
          </p>
          <Button size="sm" variant="primary" onClick={connect} disabled={busy === "connect"}>
            {busy === "connect" ? "Redirecting…" : "Connect GitHub"}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div>
      {error && <p className="mb-3 text-small text-crit">{error}</p>}

      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-body font-semibold text-ink">
          Watching {watching.length} {watching.length === 1 ? "repository" : "repositories"}
        </div>
        <div className="flex items-center gap-3 text-caption">
          <Button size="sm" variant="secondary" onClick={() => (adding ? setAdding(false) : loadAvailable())}>
            {adding ? "Done adding" : "+ Add repository"}
          </Button>
          <Button size="sm" variant="secondary" onClick={connect}>
            Reconnect
          </Button>
        </div>
      </div>

      {watching.length === 0 && !adding && (
        <p className="mb-3 text-small text-ink-dim">
          No repositories yet. <button onClick={loadAvailable} className="text-accent-text hover:underline">Add one</button> to start watching it.
        </p>
      )}

      <div className="mb-4 flex flex-col gap-2">
        {watching.map((r) => {
          const state = REPO_STATE[r.state] ?? REPO_STATE.ready;
          return (
            <div key={r.connection_id} className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface p-3">
              <div className="min-w-0">
                <div className="truncate text-small font-semibold text-ink">{r.full_name}</div>
                <div className="mt-0.5 flex flex-wrap items-center gap-2 text-micro text-ink-faint">
                  <span className={`font-mono uppercase tracking-wide ${state.tone}`}>{state.label}</span>
                  <span>· {r.signal_count} signal{r.signal_count === 1 ? "" : "s"}</span>
                  <span>· {r.last_success_at ? `synced ${new Date(r.last_success_at).toLocaleDateString()}` : "not yet synced"}</span>
                </div>
              </div>
              <div className="flex flex-none items-center gap-2.5 text-caption">
                {/* Classification is the context that decides whether this
                    repo's silence becomes a finding - critical is the only
                    level that does. */}
                <select
                  value={r.priority}
                  onChange={(e) => setPriority(r.connection_id, e.target.value)}
                  disabled={busy === r.connection_id}
                  title="How much this repository matters. Only Critical surfaces its silence as a finding."
                  className="rounded-md border border-border bg-transparent px-1.5 py-1 text-micro text-ink-dim outline-none focus:border-border-strong disabled:opacity-50"
                >
                  <option value="critical">Critical</option>
                  <option value="normal">Normal</option>
                  <option value="low">Low</option>
                  <option value="experimental">Experimental</option>
                  <option value="archived">Archived</option>
                </select>
                {r.state !== "paused" && (
                  <Button size="sm" variant="secondary" onClick={() => repoAction(r.connection_id, "sync")} disabled={busy === r.connection_id}>
                    Sync now
                  </Button>
                )}
                <Button size="sm" variant="secondary" onClick={() => repoAction(r.connection_id, r.paused ? "resume" : "pause")} disabled={busy === r.connection_id}>
                  {r.paused ? "Resume" : "Pause"}
                </Button>
                <Button size="sm" variant="danger" onClick={() => repoAction(r.connection_id, "remove")} disabled={busy === r.connection_id}>
                  Remove
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      {adding && (
        <div className="card p-4">
          <div className="mb-2 text-body font-semibold text-ink">Add a repository</div>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={`Filter ${available.length} readable repositories…`}
            className="mb-2 w-full rounded-md border border-border bg-transparent px-3 py-2 text-small outline-none focus:border-border-strong"
          />
          {addable.length === 0 ? (
            <p className="text-small text-ink-dim">
              {available.length === 0 ? "No repositories are readable with the access you granted." : "Nothing else to add — everything matching is already watched."}
            </p>
          ) : (
            <div className="flex max-h-72 flex-col gap-1 overflow-y-auto">
              {addable.map((r) => (
                <button
                  key={r.full_name}
                  onClick={() => addRepo(r.org, r.repo)}
                  disabled={busy === `${r.org}/${r.repo}`}
                  className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left text-small text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-50"
                >
                  <span className="min-w-0 truncate">{r.full_name}</span>
                  <span className="flex-none text-micro text-ink-faint">
                    {r.private ? "private" : "public"}{r.pushed_at ? ` · ${new Date(r.pushed_at).toLocaleDateString()}` : ""}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <p className="mt-3 text-caption text-ink-dim">
        🔒 PR, commit, issue and review metadata only — never source code.
      </p>
    </div>
  );
}

const CHANNEL_STATE: Record<string, { label: string; tone: string }> = {
  ready: { label: "Ready", tone: "text-good" },
  syncing: { label: "Awaiting first sync", tone: "text-ink-faint" },
  error: { label: "Sync failing", tone: "text-crit" },
  paused: { label: "Paused", tone: "text-ink-faint" },
  token_revoked: { label: "Reconnect needed", tone: "text-crit" },
  needs_setup: { label: "Not set up", tone: "text-watch" },
};

/**
 * Slack as a multi-channel provider - the same shape as GitHub's repositories.
 *
 * One bot-token grant, several monitored channels, each its own Connection so
 * each can be paused, classified or removed on its own. Managed over the shared
 * provider-account helper, not Slack-specific logic. A channel can only be
 * monitored once the bot is a member of it (invite is the access boundary).
 */
function SlackWorkspace({ connections }: { connections: Connection[] }) {
  const slack = connections.find((c) => c.provider === "slack");
  const [monitored, setMonitored] = useState<SlackChannelResource[] | null>(null);
  const [available, setAvailable] = useState<SlackChannel[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      setMonitored(await api.get<SlackChannelResource[]>("/integrations/slack/monitored"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load monitored channels");
    }
  }, []);

  useEffect(() => {
    if (slack) void load();
  }, [slack, load]);

  async function loadAvailable() {
    setAdding(true);
    try {
      setAvailable(await api.get<SlackChannel[]>("/integrations/slack/channels"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load channels");
    }
  }

  async function connect() {
    setBusy("connect");
    setError(null);
    try {
      const { ticket } = await api.post<{ ticket: string }>("/integrations/slack/connect-ticket");
      const returnTo = encodeURIComponent("/connections/slack");
      window.location.href = `${API_BASE}/integrations/slack/connect?ticket=${encodeURIComponent(ticket)}&return_to=${returnTo}`;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start the Slack connection");
      setBusy(null);
    }
  }

  async function monitorChannel(ch: SlackChannel) {
    setBusy(ch.id);
    setError(null);
    try {
      await api.post("/integrations/slack/monitored", { channel_id: ch.id, name: ch.name });
      await load();
      await loadAvailable();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start monitoring that channel");
    } finally {
      setBusy(null);
    }
  }

  async function setPriority(id: string, priority: string) {
    setBusy(id);
    setError(null);
    try {
      await api.patch(`/integrations/slack/monitored/${id}/priority`, { priority });
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function channelAction(id: string, verb: "pause" | "resume" | "remove") {
    setBusy(id);
    setError(null);
    try {
      if (verb === "remove") await api.delete(`/integrations/slack/monitored/${id}`);
      else await api.post(`/integrations/slack/monitored/${id}/${verb}`);
      await load();
      if (adding) await loadAvailable();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That didn't work");
    } finally {
      setBusy(null);
    }
  }

  if (!slack) {
    return (
      <div className="rounded-md border border-border p-6">
        <p className="text-body font-medium text-ink">Connect your Slack workspace</p>
        <p className="mt-1.5 max-w-lg text-small leading-relaxed text-ink-dim">
          Sentinel reads operational activity across the channels you choose — it never mirrors your messages,
          and it only sees channels its bot is invited to.
        </p>
        {error && <p className="mt-3 text-small text-crit">{error}</p>}
        <Button variant="primary" onClick={connect} disabled={busy === "connect"}  className="mt-4">
          {busy === "connect" ? "Starting…" : "Connect Slack"}
        </Button>
      </div>
    );
  }

  const addable = (available ?? []).filter((c) => c.is_member && !c.monitored);
  const needInvite = (available ?? []).filter((c) => !c.is_member);

  return (
    <div className="flex flex-col gap-5">
      {error && <p className="text-small text-crit">{error}</p>}

      <div className="rounded-md border border-border p-6">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span aria-hidden className="inline-block h-2 w-2 rounded-full bg-good" />
            <p className="text-body font-medium text-ink">Connected to {slack.org || "your Slack workspace"}</p>
          </div>
          <Button size="sm" variant="secondary" onClick={connect}>
            Reconnect
          </Button>
        </div>
        <p className="mt-2 max-w-lg text-small leading-relaxed text-ink-dim">
          Each monitored channel is watched independently. Sentinel never mirrors your messages — it reads a
          channel's activity to surface operational signals.
        </p>
      </div>

      {/* Monitored channels — managed like repositories. */}
      <div>
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="text-body font-semibold text-ink">
            Monitoring {monitored?.length ?? 0} {monitored?.length === 1 ? "channel" : "channels"}
          </div>
          <Button size="sm" variant="secondary" onClick={() => (adding ? setAdding(false) : loadAvailable())}>
            {adding ? "Done adding" : "+ Add channel"}
          </Button>
        </div>

        {monitored === null ? (
          <LoadingBlock />
        ) : monitored.length === 0 ? (
          <p className="mb-3 text-small text-ink-dim">
            No channels yet.{" "}
            <button onClick={loadAvailable} className="text-accent-text hover:underline">Add one</button> the bot is in to start.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {monitored.map((ch) => {
              const state = CHANNEL_STATE[ch.state] ?? CHANNEL_STATE.ready;
              return (
                <div key={ch.connection_id} className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface p-3">
                  <div className="min-w-0">
                    <div className="truncate text-small font-semibold text-ink">{ch.name}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-micro text-ink-faint">
                      <span className={`font-mono uppercase tracking-wide ${state.tone}`}>{state.label}</span>
                      <span>· {ch.signal_count} signal{ch.signal_count === 1 ? "" : "s"}</span>
                      {ch.last_sync?.at && (
                        <span>· synced {new Date(ch.last_sync.at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
                      )}
                      {ch.last_sync?.messages_scanned != null && (
                        <span>· {ch.last_sync.messages_scanned} scanned</span>
                      )}
                      {ch.last_sync?.ok === false &&
                        (ch.last_sync.error === "not_in_channel" ? (
                          <span className="text-crit">· ⚠ bot removed — re-invite @sentinel</span>
                        ) : (
                          <span className="text-crit">· last sync failed</span>
                        ))}
                    </div>
                  </div>
                  <div className="flex flex-none items-center gap-2.5 text-caption">
                    <select
                      value={ch.priority}
                      onChange={(e) => setPriority(ch.connection_id, e.target.value)}
                      disabled={busy === ch.connection_id}
                      title="How much this channel matters. Only Critical will surface its silence as a finding."
                      className="rounded-md border border-border bg-transparent px-1.5 py-1 text-micro text-ink-dim outline-none focus:border-border-strong disabled:opacity-50"
                    >
                      <option value="critical">Critical</option>
                      <option value="normal">Normal</option>
                      <option value="low">Low</option>
                      <option value="experimental">Experimental</option>
                      <option value="archived">Archived</option>
                    </select>
                    {ch.paused ? (
                      <Button size="sm" variant="secondary" onClick={() => channelAction(ch.connection_id, "resume")} disabled={busy === ch.connection_id}>
                        Resume
                      </Button>
                    ) : (
                      <Button size="sm" variant="secondary" onClick={() => channelAction(ch.connection_id, "pause")} disabled={busy === ch.connection_id}>
                        Pause
                      </Button>
                    )}
                    <Button size="sm" variant="danger" onClick={() => channelAction(ch.connection_id, "remove")} disabled={busy === ch.connection_id}>
                      Remove
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Add picker — channels the bot is in, plus an invite hint for the rest. */}
      {adding && (
        <div className="rounded-md border border-border p-4">
          <div className="mb-2.5 text-micro uppercase tracking-wide text-ink-faint">Channels the bot can monitor</div>
          {available === null ? (
            <LoadingBlock />
          ) : (
            <>
              {addable.length === 0 ? (
                <p className="text-small text-ink-faint">No new channels the bot is in. Invite it to a channel first.</p>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {addable.map((ch) => (
                    <div key={ch.id} className="flex items-center gap-3 rounded-md border border-border bg-surface px-3.5 py-2.5">
                      <span className="min-w-0 flex-1 truncate text-small text-ink">
                        <span className="text-ink-faint">#</span>{ch.name}
                        {ch.topic && <span className="ml-2 text-caption text-ink-faint">{ch.topic}</span>}
                      </span>
                      <button onClick={() => monitorChannel(ch)} disabled={busy === ch.id} className="flex-none text-caption text-accent-text hover:underline disabled:opacity-50">
                        {busy === ch.id ? "Adding…" : "Monitor"}
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {needInvite.length > 0 && (
                <p className="mt-3 text-caption text-ink-faint">
                  {needInvite.length} more channel{needInvite.length === 1 ? "" : "s"} need the bot invited —
                  <span className="font-mono text-ink-dim"> /invite @sentinel</span> in the channel, then Add again.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ComingSoonWorkspace({ label }: { label: string }) {
  return (
    <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
      {label} isn't available yet — check back soon.
    </div>
  );
}
