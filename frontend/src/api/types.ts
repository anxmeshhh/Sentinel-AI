// Mirrors backend/app/schemas/*.py - keep in sync by hand until a codegen
// step (e.g. openapi-typescript) is worth adding.

export interface Connection {
  id: string;
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

export type Severity = "crit" | "warn" | "watch";

export function severityBand(severity: number): Severity {
  if (severity >= 0.7) return "crit";
  if (severity >= 0.4) return "warn";
  return "watch";
}
