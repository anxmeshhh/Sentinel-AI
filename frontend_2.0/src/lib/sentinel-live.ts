/**
 * The live data layer.
 *
 * Every hook here returns the SAME shapes `sentinel-data.ts` exported as
 * fixtures, so the pages Lovable generated keep their markup and only change
 * where the data comes from. That is deliberate: the design was specified
 * against these shapes, and re-deriving them per page would let the two drift.
 *
 * Mapping - rather than reshaping the backend - is also deliberate. The API
 * speaks the domain's language (attention items, tiers, connection health) and
 * the UI speaks the product's (findings, severity, "Reconnect needed"). This
 * file is the one place those two vocabularies meet.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "./api";
import { useWorkspace } from "./auth";
import {
  type Finding,
  type Health,
  type MemoryItem,
  type ServiceKey,
  type Severity,
  type Situation,
  serviceByKey,
} from "./sentinel-data";

/* ------------------------------------------------------------- translation */

/** Attention priority -> the one severity ladder the whole product agrees on.
 *  These thresholds mirror services/findings.py; they are not invented here. */
function severityFromPriority(priority: number): Severity {
  if (priority >= 0.8) return "critical";
  if (priority >= 0.5) return "review";
  return "reminder";
}

function severityFromTier(tier: string): Severity {
  return tier === "critical" ? "critical" : tier === "reminder" ? "reminder" : "review";
}

/** Backend connection_state -> the health vocabulary the UI renders. */
function healthFromState(state: string | null | undefined): Health {
  switch (state) {
    case "ready":
    case "live":
      return "connected";
    case "syncing":
      return "syncing";
    case "token_revoked":
      return "reconnect";
    case "paused":
      return "paused";
    case "needs_setup":
      return "needs_setup";
    default:
      return "error";
  }
}

/** Relative time, the only format the design uses for timestamps. */
export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });
}

/** The provider string the API returns -> the service key the UI routes on.
 *  Microsoft services are named differently on each side, so the map is
 *  explicit rather than a string transform that would silently mis-route. */
const PROVIDER_TO_SERVICE: Record<string, ServiceKey> = {
  gmail: "gmail",
  google_calendar: "google_calendar",
  google_drive: "google_drive",
  github: "github",
  slack: "slack",
  zoom: "zoom",
  microsoft_outlook_mail: "microsoft_mail",
  microsoft_outlook_calendar: "microsoft_calendar",
  microsoft_todo: "microsoft_todo",
  microsoft_onedrive: "microsoft_onedrive",
  microsoft_onenote: "microsoft_onenote",
  microsoft_teams: "microsoft_teams",
};

export function serviceKeyFor(provider: string | null | undefined): ServiceKey | undefined {
  return provider ? PROVIDER_TO_SERVICE[provider] : undefined;
}

/* ------------------------------------------------------------------ shapes */

interface ApiAttentionItem {
  id: string;
  type: string;
  origin: string;
  state: "new" | "done" | "snoozed" | "dismissed";
  source_provider: string | null;
  title: string;
  why: string;
  evidence_url: string | null;
  priority: number;
  due_at: string | null;
  created_at: string;
}

interface ApiSituation {
  id: string;
  title: string;
  entity: string | null;
  entity_kind: string | null;
  severity: string;
  status: "open" | "resolved";
  member_count: number;
  cross_provider: boolean;
  occurrence_count: number;
  providers: string[];
  first_seen_at: string | null;
  last_activity_at: string | null;
  resolved_at: string | null;
}

export interface ApiSituationDetail extends ApiSituation {
  why_connected: string;
  findings: {
    id: string;
    provider: string | null;
    tier: string;
    title: string | null;
    why: string | null;
    url: string | null;
    occurred_at: string | null;
    live: boolean;
  }[];
  entities: { id: string; kind: string; name: string; role: string }[];
  reasoning: { explanation: string; recommended_actions: { action: string; grounded_in: string }[] } | null;
  memory: { id: string; summary: string; observation_count: number; first_observed_at: string | null } | null;
  decisions: {
    id: string;
    kind: "inform" | "recommend";
    action: string;
    grounded_in: string;
    rationale: string;
    requires_confirmation: boolean;
    memory_informed: boolean;
  }[];
  actions: {
    id: string;
    action_type: string;
    status: string;
    risk: string;
    verification: string | null;
    executed_at: string | null;
    undone_at: string | null;
    undo_result: string | null;
  }[];
}

interface ApiConnection {
  id: string;
  provider: string;
  org: string;
  repo: string;
  last_synced_at: string | null;
  state?: string | null;
}

interface ApiDecision {
  id: string;
  kind: "inform" | "recommend";
  action: string;
  rationale: string;
  memory_informed: boolean;
  situation_id: string | null;
  status: string;
}

interface ApiMemory {
  id: string;
  kind: string;
  summary: string;
  subject_key: string;
  observation_count: number;
  status: "active" | "forgotten";
  scope_key: string;
  first_observed_at: string | null;
  last_observed_at: string | null;
  announced_at: string | null;
}

/* ------------------------------------------------------------------- hooks */

/** Shared gate: nothing fetches until a workspace is active, because every
 *  request is scoped by the X-Workspace-Id header. */
function useReady() {
  const { active, loading } = useWorkspace();
  return { enabled: !loading && Boolean(active), workspaceId: active?.id ?? null };
}

export function useFindings() {
  const { enabled, workspaceId } = useReady();
  return useQuery({
    queryKey: ["attention", workspaceId],
    enabled,
    queryFn: async (): Promise<Finding[]> => {
      const rows = await api.get<ApiAttentionItem[]>("/attention");
      return rows.map((r) => ({
        id: r.id,
        severity: severityFromPriority(r.priority),
        status: r.state === "new" ? "open" : r.state === "snoozed" ? "snoozed" : "resolved",
        title: r.title,
        why: r.why,
        service: serviceKeyFor(r.source_provider) ?? ("gmail" as ServiceKey),
        entity: r.source_provider ?? "",
        entityKind: r.type,
        when: ago(r.created_at),
        evidence: r.evidence_url
          ? [{ what: r.title, when: ago(r.created_at), link: r.evidence_url }]
          : [],
        history: [{ when: ago(r.created_at), what: "Detected" }],
      }));
    },
  });
}

export function useSituations(status?: "open" | "resolved") {
  const { enabled, workspaceId } = useReady();
  return useQuery({
    queryKey: ["situations", workspaceId, status ?? "all"],
    enabled,
    queryFn: async (): Promise<Situation[]> => {
      const rows = await api.get<ApiSituation[]>(
        `/situations${status ? `?status=${status}` : ""}`,
      );
      return rows.map(toSituation);
    },
  });
}

function toSituation(r: ApiSituation): Situation {
  return {
    id: r.id,
    entity: r.entity ?? r.title,
    entityKind: r.entity_kind ?? "resource",
    severity: severityFromTier(r.severity),
    status: r.status,
    openedAgo: ago(r.first_seen_at),
    lastActivity: ago(r.last_activity_at),
    reasoning: "",
    connectedBecause: "",
    findingIds: Array.from({ length: r.member_count }, (_, i) => String(i)),
    providers: r.providers.map((p) => serviceKeyFor(p)).filter(Boolean) as ServiceKey[],
    recommendations: [],
    timeline: [],
    actionsTaken: [],
    // Spread rather than `undefined`: exactOptionalPropertyTypes treats
    // "present but undefined" and "absent" as different types.
    ...(r.resolved_at ? { resolvedAgo: ago(r.resolved_at) } : {}),
  };
}

/** The detail endpoint returns far more than the list shape can hold, so this
 *  hook deliberately exposes the RAW payload - the Situation page is the one
 *  surface that needs all of it. */
export function useSituation(id: string) {
  const { enabled, workspaceId } = useReady();
  return useQuery({
    queryKey: ["situation", workspaceId, id],
    enabled: enabled && Boolean(id),
    queryFn: () => api.get<ApiSituationDetail>(`/situations/${id}`),
  });
}

export function useDecisions() {
  const { enabled, workspaceId } = useReady();
  return useQuery({
    queryKey: ["decisions", workspaceId],
    enabled,
    queryFn: async () => {
      const rows = await api.get<ApiDecision[]>("/decisions");
      return rows
        .filter((d) => d.status === "proposed")
        .map((d) => ({
          id: d.id,
          text: d.action,
          rationale: d.rationale,
          kind: d.kind,
          memoryInformed: d.memory_informed,
          situationId: d.situation_id ?? undefined,
        }));
    },
  });
}

export function useMemories() {
  const { enabled, workspaceId } = useReady();
  const { active } = useWorkspace();
  return useQuery({
    queryKey: ["memory", workspaceId],
    enabled,
    queryFn: async (): Promise<MemoryItem[]> => {
      const rows = await api.get<ApiMemory[]>("/memory");
      return rows.map((m) => ({
        id: m.id,
        summary: m.summary,
        // Deterministic, never LLM prose - this is the rule that earned it.
        why: `This situation has formed, resolved and formed again — seen ${m.observation_count} times.`,
        scope: m.scope_key.startsWith("personal:") ? "personal" : "org",
        scopeName: m.scope_key.startsWith("personal:") ? "Personal" : (active?.name ?? "Workspace"),
        firstNoticed: ago(m.first_observed_at),
        lastSeen: ago(m.last_observed_at),
        evidence: [],
        forgotten: m.status === "forgotten",
        createdHoursAgo: m.first_observed_at
          ? Math.round((Date.now() - new Date(m.first_observed_at).getTime()) / 3600000)
          : 999,
      }));
    },
  });
}

/** Memories formed but never shown - drives the "Sentinel will remember that"
 *  toast, which must appear exactly once per memory. */
export function useMemoryAnnouncements() {
  const { enabled, workspaceId } = useReady();
  return useQuery({
    queryKey: ["memory-announcements", workspaceId],
    enabled,
    queryFn: () => api.get<ApiMemory[]>("/memory/announcements"),
  });
}

export interface LiveService {
  key: ServiceKey;
  name: string;
  family: string;
  familyKey: string;
  health: Health;
  account: string;
  lastSynced: string;
  connected: boolean;
  connectionId: string;
}

export function useConnections() {
  const { enabled, workspaceId } = useReady();
  return useQuery({
    queryKey: ["connections", workspaceId],
    enabled,
    queryFn: async (): Promise<LiveService[]> => {
      const rows = await api.get<ApiConnection[]>("/connections");
      return rows
        .map((c) => {
          const key = serviceKeyFor(c.provider);
          if (!key) return null;
          const meta = serviceByKey(key);
          return {
            key,
            name: meta?.name ?? c.provider,
            family: meta?.family ?? "",
            familyKey: meta?.familyKey ?? "",
            health: healthFromState(c.state),
            account: c.org,
            lastSynced: ago(c.last_synced_at),
            connected: true,
            connectionId: c.id,
          } satisfies LiveService;
        })
        .filter(Boolean) as LiveService[];
    },
  });
}

export interface ServiceIntelligence {
  service: string;
  connected: boolean;
  health: string | null;
  last_synced_at: string | null;
  account: string | null;
  findings: { id: string; title: string; why: string; tier: string; kind: string; provider: string; url: string | null }[];
  situations: {
    id: string;
    title: string;
    severity: string;
    members: number;
    cross_provider: boolean;
    explanation: string | null;
    recommendations: { action: string }[];
  }[];
  critical_count: number;
}

/** The Intelligence Rail. Provider-agnostic by construction - the endpoint
 *  filters the canonical finding stream by which providers back this service,
 *  so a new provider gets a rail without a line of new code. */
export function useServiceIntelligence(service: string) {
  const { enabled, workspaceId } = useReady();
  return useQuery({
    queryKey: ["intelligence", workspaceId, service],
    enabled: enabled && Boolean(service),
    queryFn: () => api.get<ServiceIntelligence>(`/workspace/${service}/intelligence`),
  });
}

export function useAuditActions() {
  const { enabled, workspaceId } = useReady();
  return useQuery({
    queryKey: ["audit", workspaceId],
    enabled,
    queryFn: () =>
      api.get<
        {
          id: string;
          action_type: string;
          status: string;
          risk: string;
          verification: string | null;
          created_at: string;
          executed_at: string | null;
          undone_at: string | null;
          params: Record<string, unknown>;
        }[]
      >("/workspaces/audit/actions"),
  });
}
