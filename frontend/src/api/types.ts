// Mirrors backend/app/schemas/*.py - keep in sync by hand until a codegen
// step (e.g. openapi-typescript) is worth adding.

export interface Connection {
  id: string;
  provider: "github" | "google_calendar" | "gmail" | "google_drive";
  org: string;
  repo: string;
  last_synced_at: string | null;
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

export interface CalendarPlan {
  title: string;
  start: string;
  end: string;
  action: string;
}

export interface AttentionItem {
  id: string;
  type: "important_email" | "upcoming_meeting" | "stale_pr" | "finding" | "manual" | "deadline";
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
