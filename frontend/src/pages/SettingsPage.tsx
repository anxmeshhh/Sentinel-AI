import type { FormEvent, ReactNode } from "react";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Connection } from "../api/types";

const AGENTS = [
  { name: "Engineering", desc: "GitHub bottlenecks, hotspots, inactive contributors, risky deploys", tag: "PHASE 1", on: true },
  { name: "Executive", desc: "Synthesizes every agent's findings into the daily brief", tag: "ALWAYS ON", on: true },
  { name: "Project", desc: "Jira / Linear sprint risk & deadline-slip prediction", tag: "PHASE 2", on: false },
  { name: "Communication", desc: "Slack gaps, missing approvals, unanswered questions", tag: "PHASE 3", on: false },
  { name: "Knowledge", desc: "Stale or missing docs across Notion / Confluence", tag: "PHASE 3", on: false },
  { name: "DevOps · Security · Finance", desc: "Deploy risk, secret exposure, cost anomalies", tag: "PHASE 4", on: false },
  { name: "HR Wellbeing", desc: "Team-level workload patterns only — never individual judgment. Opt-in, off by default.", tag: "OPT-IN", on: false },
];

export function SettingsPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [org, setOrg] = useState("");
  const [repo, setRepo] = useState("");
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    api.get<Connection[]>("/connections").then(setConnections);
  }

  useEffect(load, []);

  async function handleConnect(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/connections", { org, repo, github_token: token });
      setOrg("");
      setRepo("");
      setToken("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to connect repository");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDisconnect(id: string) {
    await api.delete(`/connections/${id}`);
    load();
  }

  return (
    <div className="max-w-2xl">
      <h1 className="mb-1 text-xl font-semibold text-balance">Agents &amp; Connections</h1>
      <p className="mb-7 text-[13px] text-ink-dim">
        Control what Sentinel watches and which agents are allowed to run.
      </p>

      <SectionLabel>Connections</SectionLabel>
      <div className="mb-3 rounded-md border border-border bg-surface">
        {connections.length === 0 ? (
          <p className="p-4 text-[13px] text-ink-dim">No repository connected yet.</p>
        ) : (
          connections.map((c) => (
            <div key={c.id} className="flex items-center gap-3 border-b border-border p-3.5 last:border-b-0">
              <div>
                <div className="font-mono text-[12.5px] font-semibold">
                  {c.org}/{c.repo}
                </div>
                <div className="text-[11.5px] text-ink-faint">
                  GitHub · {c.last_synced_at ? `synced ${new Date(c.last_synced_at).toLocaleString()}` : "not yet synced"}
                </div>
              </div>
              <button
                onClick={() => handleDisconnect(c.id)}
                className="ml-auto rounded-md border border-crit px-2.5 py-1 font-mono text-[11.5px] text-crit hover:bg-crit/10"
              >
                DISCONNECT
              </button>
            </div>
          ))
        )}
      </div>

      <form onSubmit={handleConnect} className="mb-8 rounded-md border border-border bg-surface p-4">
        <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <input
            required
            placeholder="org (e.g. northwind)"
            value={org}
            onChange={(e) => setOrg(e.target.value)}
            className="rounded-md border border-border bg-ground px-3 py-2 text-[13px] outline-none focus:border-accent"
          />
          <input
            required
            placeholder="repo (e.g. checkout-service)"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            className="rounded-md border border-border bg-ground px-3 py-2 text-[13px] outline-none focus:border-accent"
          />
        </div>
        <input
          required
          type="password"
          placeholder="GitHub personal access token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="mb-3 w-full rounded-md border border-border bg-ground px-3 py-2 text-[13px] outline-none focus:border-accent"
        />
        {error && <p className="mb-2 text-[12.5px] text-crit">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-accent py-2.5 text-[13.5px] font-bold text-ground disabled:opacity-50"
        >
          {submitting ? "Connecting…" : "Connect repository"}
        </button>
        <p className="mt-2.5 text-[12px] text-ink-dim">
          🔒 Sentinel reads PR, commit, issue, and review metadata only — never source code.
        </p>
      </form>

      <SectionLabel>Agents</SectionLabel>
      <div className="rounded-md border border-border bg-surface">
        {AGENTS.map((agent) => (
          <div key={agent.name} className="flex items-center gap-3.5 border-b border-border p-3 last:border-b-0">
            <div>
              <div className="text-[13.5px] font-semibold">{agent.name}</div>
              <div className="mt-0.5 text-[12px] text-ink-faint">{agent.desc}</div>
            </div>
            <span className="ml-auto whitespace-nowrap rounded-full border border-border px-2 py-[3px] font-mono text-[10px] text-ink-faint">
              {agent.tag}
            </span>
            <div className={`h-[19px] w-[34px] flex-none rounded-full ${agent.on ? "bg-accent" : "bg-border"}`}>
              <div
                className={`h-[15px] w-[15px] translate-y-[2px] rounded-full bg-surface transition-transform ${
                  agent.on ? "translate-x-[17px]" : "translate-x-[2px]"
                }`}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-2.5 font-mono text-[13px] font-bold uppercase tracking-wide text-ink-dim">{children}</div>
  );
}
