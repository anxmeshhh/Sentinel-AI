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

export interface Team {
  id: string;
  workspace_id: string;
  name: string;
  slug: string;
  member_count: number;
  is_member: boolean;
}

export interface MyTeam {
  id: string;
  workspace_id: string;
  workspace_name: string;
  name: string;
  slug: string;
  member_count: number;
  role: string;
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
  organizer: string | null;
  has_meeting_link: boolean;
  url: string | null;
}

export type Severity = "crit" | "warn" | "watch";

export function severityBand(severity: number): Severity {
  if (severity >= 0.7) return "crit";
  if (severity >= 0.4) return "warn";
  return "watch";
}
