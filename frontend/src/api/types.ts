// Mirrors backend/app/schemas/*.py - keep in sync by hand until a codegen
// step (e.g. openapi-typescript) is worth adding.

export interface Connection {
  id: string;
  provider: "github" | "google_calendar" | "gmail" | "google_drive" | "slack" | "microsoft_outlook_mail" | "microsoft_outlook_calendar" | "microsoft_teams";
  org: string;
  repo: string;
  last_synced_at: string | null;
  // Real health: ready | live | syncing | error | token_revoked | paused | needs_setup
  state?: string | null;
}

/** A repository the connected GitHub token can actually read.
 *  Offered as a choice rather than typed: a hand-entered repo name is a
 *  guess that fails silently at the first sync. */
export interface GitHubRepo {
  org: string;
  repo: string;
  full_name: string;
  private: boolean;
  pushed_at: string | null;
  monitored: boolean;
  connection_id: string | null;
}

/** One repository Sentinel is watching, with its own health - the management
 *  view. Multi-repo means each carries its own sync state and signal count. */
export interface GitHubRepository {
  connection_id: string;
  org: string;
  repo: string;
  full_name: string;
  state: "ready" | "syncing" | "error" | "paused" | "token_revoked" | "needs_setup";
  paused: boolean;
  last_synced_at: string | null;
  last_success_at: string | null;
  signal_count: number;
  /** How much this repo matters, set by a person. Only 'critical' makes a
   *  repo's silence a proactive finding. */
  priority: "critical" | "normal" | "low" | "archived" | "experimental";
}

export interface Finding {
  id: string;
  run_id: string;
  agent: string;
  type: string;
  severity: number;
  confidence: number;
  summary: string;
  root_cause: string;
  suggested_action: string;
  evidence: Record<string, unknown>;
  created_at: string;
}

export interface Brief {
  id: string;
  run_id: string;
  generated_at: string;
  narrative: string;
  top_finding_ids: string[];
  data_freshness: Record<string, string>;
  findings: Finding[];
}

export interface BriefSummary {
  id: string;
  generated_at: string;
  narrative: string;
}

export interface AgentRun {
  id: string;
  connection_id: string | null;
  connection_label: string | null;
  status: "running" | "success" | "partial" | "failed";
  triggered_by: "schedule" | "manual";
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  node_errors: Record<string, string>;
  error: string | null;
  finding_count: number;
}

export interface LogLine {
  timestamp: string | null;
  level: string | null;
  logger: string | null;
  event: string | null;
  run_id: string | null;
  workspace_id: string | null;
  agent: string | null;
  connection_id: string | null;
  raw: Record<string, unknown>;
}

export interface SystemStats {
  connections: number;
  signals: number;
  findings: number;
  briefs: number;
  runs_total: number;
  runs_success: number;
  runs_partial: number;
  runs_failed: number;
  runs_running: number;
}

export type ChannelPrivacy = "public" | "invite_only" | "private";

export interface Team {
  id: string;
  workspace_id: string;
  name: string;
  slug: string;
  member_count: number;
  is_member: boolean;
  my_channel_role: "channel_admin" | "channel_member" | null;
  description: string | null;
  icon: string | null;
  category: string | null;
  privacy: ChannelPrivacy;
  is_archived: boolean;
}

export interface WorkspaceMember {
  user_id: string;
  name: string;
  email: string;
  role: string;
}

export interface MyTeam {
  id: string;
  workspace_id: string;
  workspace_name: string;
  name: string;
  slug: string;
  member_count: number;
  role: string; // workspace-level role
  channel_role: "channel_admin" | "channel_member";
}

export interface TeamMember {
  user_id: string;
  name: string;
  email: string;
  channel_role: "channel_admin" | "channel_member";
}

export interface ChannelConnectionResource {
  id: string;
  resource_key: string;
  resource_label: string;
}

export interface ChannelConnection {
  id: string;
  team_id: string;
  connection_id: string;
  provider: string;
  label: string;
  resources: ChannelConnectionResource[];
}

export interface ChannelAIHistoryItem {
  id: string;
  user_id: string;
  user_name: string;
  command: string;
  reply: string;
  created_at: string;
}

export interface Invite {
  token: string;
  workspace_id: string;
  team_id: string | null;
  expires_at: string | null;
  max_uses: number | null;
  used_count: number;
}

export interface InviteAcceptResult {
  workspace_id: string;
  team_id: string | null;
}

export interface InvitePreview {
  workspace_name: string;
  team_name: string | null;
  invited_by_name: string;
  valid: boolean;
  reason_invalid: string | null;
}

export interface MailItem {
  id: string;
  thread_id: string | null;
  subject: string;
  sender: string;
  to: string | null;
  occurred_at: string;
  is_starred: boolean;
  is_important: boolean;
  is_unread: boolean;
  is_spam: boolean;
  url: string;
}

export interface MailBody {
  subject: string;
  sender: string;
  body_text: string | null;
  url: string;
  fetched_live: boolean;
}

export interface MailSummary {
  subject: string;
  sender: string;
  summary: string;
  key_points: string[];
  action_items: string[];
  body_text: string | null;
  url: string;
  cached: boolean;
}

export interface DriveFile {
  id: string;
  name: string;
  mime_type: string | null;
  modified_at: string | null;
  url: string | null;
  owner: string | null;
  shared: boolean;
  size_bytes: number | null;
}

export interface DriveAnalytics {
  recent_files: DriveFile[];
  shared_files: DriveFile[];
  type_counts: Record<string, number>;
  large_files: DriveFile[];
  storage_used_bytes: number | null;
  storage_limit_bytes: number | null;
}

export interface MailAskResult {
  matched_filter: string | null;
  matched_category: string | null;
  items: MailItem[];
  message: string | null;
}

export interface CalendarEvent {
  id: string;
  title: string;
  start: string | null;
  end: string | null;
  occurred_at: string;
  attendee_count: number;
  attendee_emails: string[];
  organizer: string | null;
  has_meeting_link: boolean;
  meet_url: string | null;
  status: string;
  url: string | null;
}

export type HolidayCategory = "national" | "regional" | "festival" | "observance";

export interface Holiday {
  title: string;
  date: string;
  category: HolidayCategory;
  states: string[] | null;
}

export interface BriefSource {
  kind: "meeting" | "email" | "document" | "prior_meeting";
  label: string;
  url: string | null;
}

export interface MeetingBrief {
  id: string;
  title: string;
  narrative: string;
  prep_points: string[];
  sources: BriefSource[];
  created_at: string;
  cached: boolean;
}

/** One verified fact behind an investigation. Retrieved from Signals -
 *  never written by the model, which is what makes it checkable. */
export interface Evidence {
  signal_id: string;
  kind: string;
  title: string;
  actor: string | null;
  occurred_at: string | null;
  url: string | null;
  relation: "same_thread" | "same_correspondent" | "shared_subject" | "around_the_same_time";
  relation_label: string;
}

export interface Investigation {
  id: string;
  attention_item_id: string;
  title: string;
  /** The four fields below are the model's reading of `evidence`. */
  what_happened: string;
  why_it_matters: string;
  contributing_factors: string[];
  next_steps: string[];
  confidence: number;
  evidence: Evidence[];
  llm_calls: number;
  created_at: string;
}

/** Something Sentinel wants to do, or did. Named SentinelAction because
 *  `Action` collides with DOM and React vocabulary. */
export interface SentinelAction {
  id: string;
  action_type: string;
  risk: "low" | "medium" | "high";
  status:
    | "proposed"
    | "awaiting_approval"
    | "approved"
    | "executing"
    | "succeeded"
    | "failed"
    | "unknown"
    | "rejected"
    | "cancelled";
  params: Record<string, unknown>;
  /** Exactly what the user was shown before approving - stored server-side,
   *  so the record proves what they agreed to. */
  preview: { title?: string; fields?: Record<string, unknown>; effect?: string };
  reason: string | null;
  source_kind: string | null;
  source_id: string | null;
  requested_by_user_id: string;
  approved_by_user_id: string | null;
  approved_at: string | null;
  executed_at: string | null;
  result: Record<string, unknown>;
  error: string | null;
  /** How the outcome was confirmed. A success without this is not reported
   *  as a success. */
  verification: string | null;
  /** Undo is recorded, never erased: "done and then taken back" is a
   *  different fact from "never happened". */
  undone_at: string | null;
  undone_by_user_id: string | null;
  /** What the compensator achieved - including when it could not fully undo
   *  the effect, e.g. an invitation that was already delivered. */
  undo_result: string | null;
  created_at: string;
}

/** A desired outcome, plus whether the evidence says it will happen.
 *  `health` and `progress` are computed from linked evidence - the model
 *  explains them, it never decides them. `progress` is null when nothing is
 *  linked, which is a real answer rather than a confident 0%. */
export interface Goal {
  id: string;
  title: string;
  outcome: string | null;
  due_at: string | null;
  health: "unknown" | "on_track" | "at_risk" | "blocked" | "achieved" | "abandoned";
  progress: number | null;
  /** Why the health is what it is - deterministic, checkable. */
  health_reasons: string[];
  assessment: string | null;
  next_step: string | null;
  llm_calls: number;
  closed_at: string | null;
  created_at: string;
}

export interface ActionCatalogEntry {
  key: string;
  label: string;
  risk: string;
  scopes: string[];
  external: boolean;
  needs_approval: boolean;
  available: boolean;
  unavailable_reason: string | null;
  requires_channel_admin: boolean;
  /** What Sentinel can honestly promise about undoing it. */
  reversibility: "reversible" | "compensatable" | "irreversible";
  /** Whether it could ever run unattended - and even then only after an
   *  explicit per-scope opt-in. */
  autonomy_eligible: boolean;
}

export interface ActionPolicy {
  action_type: string;
  enabled: boolean;
  daily_limit: number;
  enabled_at: string | null;
}

export interface GoalEvidenceItem {
  kind: string;
  id: string;
  title: string;
  detail: string;
}

/** Offered, never applied. A wrong link silently changes a goal's health,
 *  so suggesting and linking have deliberately different bars. */
export interface SuggestedCommitment {
  commitment_id: string;
  what: string;
  status: string;
  due_at: string | null;
  shared_terms: string[];
  reason: string;
}

export interface GoalDetail extends Goal {
  commitments: {
    id: string;
    what: string;
    status: string;
    owner_label: string | null;
    due_at: string | null;
    /** How much of the goal this represents. 1.0 unless someone said otherwise. */
    weight: number;
  }[];
  blockers: GoalEvidenceItem[];
  risks: GoalEvidenceItem[];
  suggested_commitments: SuggestedCommitment[];
}

export interface CommitmentEvidence {
  signal_id: string;
  kind: string;
  title: string;
  actor: string | null;
  occurred_at: string;
  url: string | null;
  relation: string;
}

/** Something someone said would happen, tracked until it does. Not a task:
 *  it carries the evidence it came from, and its lifecycle is driven by
 *  dates and source state rather than by ticking a box. */
export interface Commitment {
  id: string;
  source: "manual" | "tracked" | "extracted";
  status: "suggested" | "pending" | "due_soon" | "at_risk" | "overdue" | "resolved" | "dismissed";
  what: string;
  owner_label: string | null;
  due_at: string | null;
  evidence: CommitmentEvidence[];
  last_progress_at: string | null;
  confidence: number;
  resolved_at: string | null;
  resolution_reason: string | null;
  created_at: string;
}

/** One signal Sentinel actually observed. FACT - never model-written. */
export interface SituationEvidence {
  signal_id: string;
  kind: string;
  title: string;
  actor: string | null;
  occurred_at: string;
  url: string | null;
  relation: string;
}

/** A developing situation Sentinel noticed without being asked. Distinct
 *  from an AttentionItem: that is one thing that arrived, this is a reading
 *  of several signals over time, with a lifecycle. */
export interface Situation {
  id: string;
  situation_key: string;
  kind: "service_jeopardy" | "meeting_unprepared";
  status: "emerging" | "active" | "resolved";
  title: string;
  evidence: SituationEvidence[];
  evidence_count: number;
  first_seen_at: string;
  last_evidence_at: string;
  /** Deterministic, not model-assigned. */
  importance: number;
  confidence: number;
  /** INFERENCE + RECOMMENDATION. Null until the situation earns an LLM call. */
  what_is_developing: string | null;
  why_it_matters: string | null;
  suggested_next_steps: string[];
  llm_calls: number;
  /** The attention item to hand to Investigate This, when one of this
   *  situation's signals also produced one. Null means the deeper
   *  investigation isn't available for this situation - the UI omits the
   *  action rather than offering a button that cannot work. */
  investigatable_item_id: string | null;
}

export interface CalendarPlan {
  title: string;
  start: string;
  end: string;
  action: string;
}

export interface AttentionItem {
  id: string;
  type:
    | "important_email"
    | "upcoming_meeting"
    | "stale_pr"
    | "finding"
    | "manual"
    | "deadline"
    | "conversation_mention"
    | "conversation_blocker"
    | "conversation_urgent";
  origin: "detected" | "manual";
  state: "new" | "done" | "snoozed" | "dismissed";
  source_provider: string | null;
  title: string;
  why: string;
  evidence_url: string | null;
  priority: number;
  due_at: string | null;
  snoozed_until: string | null;
  created_at: string;
}

export type Persona = "individual" | "developer" | "team" | "business" | "explorer";

export interface OnboardingState {
  persona: Persona | null;
  onboarded_at: string | null;
  suggested_providers: string[];
  show_channels: boolean;
}

export interface DemoWorkspace {
  workspace_id: string;
  name: string;
  signals_seeded: number;
}

export interface ChannelBriefing {
  items: AttentionItem[];
  narrative: string | null;
  connection_labels: string[];
  no_connections: boolean;
  /** Required integrations *you* haven't connected. Distinguishes "nothing
   *  needs attention" from "you're not set up yet". */
  blocking_providers: string[];
}

export type ReadinessState = "not_connected" | "syncing" | "ready" | "expired" | "needs_setup";

/** What an admin declared this channel needs - a provider, never an account. */
export interface ChannelRequirement {
  id: string;
  provider: string;
  is_required: boolean;
  reason: string | null;
}

export interface RequirementStatus {
  provider: string;
  is_required: boolean;
  reason: string | null;
  state: ReadinessState;
  /** The account the *viewer* connected. Never another member's. */
  account_label: string | null;
  /** The tier that already shares this provider with the channel, if any.
   *  A tier name ("workspace"), never an account - when set, the member has
   *  nothing to do, and their own connection becomes optional and private. */
  provided_by: "workspace" | "class" | "group" | "channel" | null;
}

export interface ChannelReadiness {
  team_id: string;
  is_ready: boolean;
  blocking_providers: string[];
  requirements: RequirementStatus[];
}

export interface MemberReadiness {
  user_id: string;
  name: string | null;
  email: string;
  role: string;
  is_ready: boolean;
  requirements: {
    provider: string;
    is_required: boolean;
    state: ReadinessState;
    account_label: string | null;
    provided_by: "workspace" | "class" | "group" | "channel" | null;
  }[];
}

export interface AttentionContext {
  connection_count: number;
  synced_connection_count: number;
  last_synced_at: string | null;
  signals_seen: number;
  considered: number;
  filtered_as_noise: number;
}

export interface SlackChannel {
  id: string;
  name: string;
  is_member: boolean;
  num_members: number | null;
  topic: string;
  purpose: string;
  monitored: boolean;
}

export interface SlackSyncMeta {
  ok: boolean;
  signals?: number;
  messages_scanned?: number;
  participants?: number;
  duration_ms?: number;
  at?: string;
  error?: string;
}

export interface SlackChannelResource {
  connection_id: string;
  channel_id: string;
  name: string;
  state: string;
  paused: boolean;
  priority: string;
  last_synced_at: string | null;
  last_success_at: string | null;
  signal_count: number;
  last_sync: SlackSyncMeta | null;
}

export interface ProviderStatus {
  provider: string;
  label: string;
  ok: boolean;
  state: string;
  resource_count: number;
  signal_count: number;
  live: boolean;
  error: string | null;
  last_synced_at: string | null;
  note: string | null;
}

export interface SentinelStatus {
  healthy: boolean;
  provider_count: number;
  resource_count: number;
  signals_analysed: number;
  findings_count: number;
  critical_count: number;
  review_count: number;
  reminder_count: number;
  summary: string | null;
  last_synced_at: string | null;
  providers: ProviderStatus[];
  errors: string[];
}

export interface CatchUp {
  since: string;
  gap_hours: number;
  narrative: string | null;
  facts: Record<string, unknown>;
}

export type Severity = "crit" | "warn" | "watch";

export function severityBand(severity: number): Severity {
  if (severity >= 0.7) return "crit";
  if (severity >= 0.4) return "warn";
  return "watch";
}

// --- Phase 2y: Workspace -> Class -> Group -> Channel ---------------------

export interface WorkspaceClass {
  id: string;
  workspace_id: string;
  name: string;
  slug: string;
  description: string | null;
  icon: string | null;
  position: number;
  group_count: number;
}

export interface HierarchyGroup {
  id: string;
  class_id: string;
  name: string;
  slug: string;
  description: string | null;
  icon: string | null;
  position: number;
  channel_count: number;
}

export interface TreeChannel {
  id: string;
  name: string;
  slug: string;
  icon: string | null;
  privacy: ChannelPrivacy;
  is_member: boolean;
  member_count: number;
}

export interface TreeGroup {
  id: string;
  name: string;
  slug: string;
  icon: string | null;
  description: string | null;
  channels: TreeChannel[];
}

export interface TreeClass {
  id: string;
  name: string;
  slug: string;
  icon: string | null;
  description: string | null;
  groups: TreeGroup[];
}

/** Breadcrumb: Workspace / Class / Group / #Channel. */
export interface ChannelPath {
  workspace_id: string;
  workspace_name: string;
  class_id: string;
  class_name: string;
  group_id: string;
  group_name: string;
  channel_id: string;
  channel_name: string;
}

export interface ChannelFeedItem {
  id: string;
  type: string;
  type_label: string;
  title: string;
  actor: string | null;
  provider: string;
  source_label: string;
  url: string | null;
  occurred_at: string;
}

export interface ChannelFeed {
  items: ChannelFeedItem[];
  no_connections: boolean;
  connection_labels: string[];
}

// --- The three built-out channel modules ---------------------------------

export interface ChannelInsights {
  no_connections: boolean;
  window_days: number;
  total: number;
  connection_labels: string[];
  by_type: { type: string; label: string; count: number }[];
  top_actors: { actor: string; count: number }[];
  busiest_day: { date: string; count: number } | null;
}

export interface KnowledgeDoc {
  id: string;
  title: string;
  url: string | null;
  owner: string | null;
  modified_at: string;
  source_label: string;
}

export interface ChannelKnowledge {
  no_connections: boolean;
  documents: KnowledgeDoc[];
  connection_labels: string[];
}

export interface UpcomingMeeting {
  signal_id: string;
  external_id: string;
  title: string;
  start: string | null;
  attendee_count: number;
  url: string | null;
}

export interface ChannelPrepare {
  no_connections: boolean;
  meetings: UpcomingMeeting[];
}

// --- Phase 2z: shared connections at Class / Group ------------------------

export interface SharedConnectionResource {
  id: string;
  resource_key: string;
  resource_label: string;
}

export interface SharedConnection {
  id: string;
  scope_type: "class" | "group";
  scope_id: string;
  connection_id: string;
  provider: string;
  label: string;
  resources: SharedConnectionResource[];
}

/** What a channel can actually use, across all three tiers. */
export interface AuthorizedConnection {
  connection_id: string;
  provider: string;
  label: string;
  source: "channel" | "group" | "class";
  resources: string[];
}

/** A connection a channel has opted out of. Grants nothing - subtractive only. */
export interface ChannelExclusion {
  id: string;
  connection_id: string;
  provider: string;
  label: string;
  reason: string | null;
}

/** One Microsoft service and what the connected account can do with it.
 *  `available` is a CAPABILITY (does this account type include it), not health -
 *  an unavailable service is explained, never shown as an error. */
export interface MicrosoftService {
  key: string;
  label: string;
  description: string;
  available: boolean;
  status: string;
  reason: string | null;
  unlock: string | null;
  connected: boolean;
}

export interface MicrosoftCapabilities {
  connected: boolean;
  account_type: string;
  account_type_label: string;
  account: string | null;
  tenant_name: string | null;
  services: MicrosoftService[];
}

/** One finding on a service's intelligence rail. */
export interface ServiceFinding {
  id: string;
  title: string;
  why: string;
  tier: string;
  kind: string;
  provider: string | null;
  url: string | null;
}

export interface ServiceSituation {
  id: string;
  title: string;
  severity: string;
  members: number;
  cross_provider: boolean;
  explanation: string | null;
  recommendations: { action: string; grounded_in?: string }[];
}

/** The provider-agnostic payload behind every workspace page's rail. */
export interface ServiceIntelligence {
  service: string;
  connected: boolean;
  health: string | null;
  last_synced_at: string | null;
  account: string | null;
  findings: ServiceFinding[];
  situations: ServiceSituation[];
  critical_count: number;
}

/** Mirrors backend ActionOut - the Action Registry's record of one write. */
export interface ActionResult {
  id: string;
  action_type: string;
  risk: string;
  status: string;
  preview: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string | null;
  verification: string | null;
  undone_at: string | null;
}

export interface OutlookMailItem {
  id: string;
  message_id: string;
  subject: string;
  from: string;
  to: string | null;
  occurred_at: string | null;
  unread: boolean;
  important: boolean;
  flagged: boolean;
  bulk: boolean;
  thread_id: string | null;
  url: string | null;
}

export interface OutlookMailBody {
  message_id: string;
  subject: string;
  from: string | null;
  to: string | null;
  body_text: string;
  is_read: boolean;
  flagged: boolean;
  url: string | null;
}

export interface OutlookEvent {
  id: string;
  event_id: string;
  title: string;
  start: string | null;
  end: string | null;
  attendee_count: number;
  attendee_emails: string[];
  organizer: string | null;
  has_meeting_link: boolean;
  meet_url: string | null;
  status: string;
  url: string | null;
  day: string | null;
}

export interface OutlookCalendar {
  events: OutlookEvent[];
  /** Overlaps computed server-side, so the page and the assistant agree. */
  conflicts: { a: string; b: string; when: string }[];
  account: string | null;
}

export interface TodoTask {
  id: string;
  list_id: string;
  list: string;
  title: string;
  notes: string;
  completed: boolean;
  importance: string;
  due_at: string | null;
  /** Computed server-side so the page and the detectors agree on "overdue". */
  bucket: "overdue" | "today" | "upcoming" | "someday" | "completed";
}

export interface TodoBoard {
  tasks: TodoTask[];
  lists: { id: string; name: string; default: boolean }[];
  counts: Record<string, number>;
  account: string | null;
}

export interface DriveItem {
  id: string;
  name: string;
  is_folder: boolean;
  child_count: number | null;
  size: number | null;
  mime_type: string | null;
  modified_at: string | null;
  modified_by: string;
  shared: boolean;
  parent_id: string | null;
  url: string | null;
}

export interface DriveBrowse {
  items: DriveItem[];
  folder: DriveItem | null;
  searching: boolean;
  account: string | null;
}

export interface NotePage {
  id: string;
  title: string;
  modified_at: string | null;
  url: string | null;
}

export interface NoteBrowse {
  notebooks: { id: string; name: string; url: string | null }[];
  sections: { id: string; name: string; notebook_id: string }[];
  pages: NotePage[];
  account: string | null;
}
