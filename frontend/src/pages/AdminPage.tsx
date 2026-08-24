import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { AgentRun, LogLine, SystemStats } from "../api/types";
import { BackNav } from "../components/BackNav";
import { Button, Icon, PageHeader } from "../components/ui";

const POLL_MS = 5000;

const STATUS_CLASSES: Record<AgentRun["status"], string> = {
  success: "bg-good/15 text-good",
  partial: "bg-warn/15 text-warn",
  failed: "bg-crit/15 text-crit",
  running: "bg-watch/15 text-watch",
};

const LEVEL_CLASSES: Record<string, string> = {
  error: "text-crit",
  warning: "text-warn",
  info: "text-ink-dim",
  debug: "text-ink-faint",
};

export function AdminPage() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function loadAll() {
    const [s, r, l] = await Promise.all([
      api.get<SystemStats>("/admin/stats"),
      api.get<AgentRun[]>("/admin/runs?limit=50"),
      api.get<LogLine[]>("/admin/logs?limit=200"),
    ]);
    setStats(s);
    setRuns(r);
    setLogs(l);
  }

  useEffect(() => {
    loadAll();
  }, []);

  useEffect(() => {
    if (autoRefresh) {
      timerRef.current = setInterval(loadAll, POLL_MS);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [autoRefresh]);

  return (
    <div>
      <BackNav back={{ to: "/", label: "Dashboard" }} />
      <PageHeader
        eyebrow="Operator"
        title="Admin & Observability"
        description="Operator view — agent run history, system counts, and live logs. Not part of the customer-facing product."
        actions={
        <div className="flex items-center gap-2.5">
          <label className="flex items-center gap-1.5 text-caption text-ink-dim">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            auto-refresh (5s)
          </label>
          <Button size="sm" variant="secondary" onClick={loadAll}>
            <Icon name="refresh" size={13} /> Refresh
          </Button>
        </div>
        }
      />

      {stats && <StatsRow stats={stats} />}

      <SectionLabel>Agent Runs</SectionLabel>
      <RunsTable runs={runs} />

      <SectionLabel>Logs (live tail)</SectionLabel>
      <LogViewer logs={logs} />
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="label-sub mb-2.5 mt-6 text-body font-bold text-ink-dim">
      {children}
    </div>
  );
}

function StatsRow({ stats }: { stats: SystemStats }) {
  const tiles = [
    { label: "Connections", value: stats.connections },
    { label: "Signals", value: stats.signals },
    { label: "Findings", value: stats.findings },
    { label: "Briefs", value: stats.briefs },
    { label: "Runs (success)", value: stats.runs_success, cls: "text-good" },
    { label: "Runs (partial)", value: stats.runs_partial, cls: "text-warn" },
    { label: "Runs (failed)", value: stats.runs_failed, cls: "text-crit" },
  ];
  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7">
      {tiles.map((t) => (
        <div key={t.label} className="card p-3">
          <div className="label-sub">{t.label}</div>
          <div className={`tab-nums font-mono text-h3 font-bold ${t.cls ?? ""}`}>{t.value}</div>
        </div>
      ))}
    </div>
  );
}

function RunsTable({ runs }: { runs: AgentRun[] }) {
  if (runs.length === 0) {
    return <p className="text-body text-ink-dim">No agent runs yet.</p>;
  }
  return (
    <div className="overflow-x-auto card">
      <table className="w-full min-w-[720px] border-collapse text-small">
        <thead>
          <tr>
            {["Status", "Connection", "Trigger", "Started", "Duration", "Findings", "Error"].map((h) => (
              <th
                key={h}
                className="label-sub border-b border-border px-3 py-2 text-left"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td className="border-b border-border px-3 py-2">
                <span className={`rounded-full px-2 py-[3px] font-mono text-caption font-bold uppercase ${STATUS_CLASSES[run.status]}`}>
                  {run.status}
                </span>
              </td>
              <td className="border-b border-border px-3 py-2 text-ink-dim">
                {run.connection_label ?? "—"}
              </td>
              <td className="border-b border-border px-3 py-2 text-ink-faint">{run.triggered_by}</td>
              <td className="tab-nums border-b border-border px-3 py-2 text-ink-dim">
                {new Date(run.started_at).toLocaleString()}
              </td>
              <td className="tab-nums border-b border-border px-3 py-2 text-ink-dim">
                {run.duration_seconds != null ? `${run.duration_seconds.toFixed(1)}s` : "—"}
              </td>
              <td className="tab-nums border-b border-border px-3 py-2 text-ink-dim">{run.finding_count}</td>
              <td className="max-w-xs truncate border-b border-border px-3 py-2 text-crit" title={run.error ?? undefined}>
                {run.error ?? (Object.keys(run.node_errors).length > 0 ? Object.values(run.node_errors).join("; ") : "—")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LogViewer({ logs }: { logs: LogLine[] }) {
  if (logs.length === 0) {
    return <p className="text-body text-ink-dim">No logs captured yet.</p>;
  }
  return (
    <div className="max-h-[420px] overflow-y-auto rounded-md border border-border bg-ground p-3 text-small">
      {logs.map((log, i) => (
        <div key={i} className="mb-1 flex gap-2 border-b border-border/50 pb-1 last:border-b-0">
          <span className="tab-nums whitespace-nowrap text-ink-faint">
            {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : "—"}
          </span>
          <span className={`w-14 flex-none uppercase ${LEVEL_CLASSES[log.level ?? ""] ?? "text-ink-dim"}`}>
            {log.level ?? ""}
          </span>
          <span className="w-40 flex-none truncate text-ink-faint">{log.logger}</span>
          <span className="flex-1 text-ink">
            {log.event}
            {log.run_id && <span className="ml-2 text-ink-faint">run={log.run_id.slice(0, 8)}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}
