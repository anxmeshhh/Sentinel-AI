import type { FormEvent, ReactNode } from "react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { Connection } from "../api/types";

const GOOGLE_ERROR_MESSAGES: Record<string, string> = {
  session_expired: "That connect link expired — try again.",
  no_refresh_token: "Google didn't grant offline access — try disconnecting in your Google Account settings and reconnecting.",
};

const AGENTS = [
  { name: "Engineering", desc: "GitHub bottlenecks, hotspots, inactive contributors, risky deploys", tag: "PHASE 1", on: true },
  { name: "Communication", desc: "Stale flagged mail, spam surges, calendar overload — from Gmail/Calendar", tag: "PHASE 2", on: true },
  { name: "Executive", desc: "Synthesizes every agent's findings into the daily brief", tag: "ALWAYS ON", on: true },
  { name: "Project", desc: "Jira / Linear sprint risk & deadline-slip prediction", tag: "PHASE 2", on: false },
  { name: "Knowledge", desc: "Stale or missing docs across Notion / Confluence", tag: "PHASE 3", on: false },
  { name: "DevOps · Security · Finance", desc: "Deploy risk, secret exposure, cost anomalies", tag: "PHASE 4", on: false },
  { name: "HR Wellbeing", desc: "Team-level workload patterns only — never individual judgment. Opt-in, off by default.", tag: "OPT-IN", on: false },
];

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [expandedGroup, setExpandedGroup] = useState<string | null>("google");
  const [org, setOrg] = useState("");
  const [repo, setRepo] = useState("");
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [googleConnecting, setGoogleConnecting] = useState(false);

  function load() {
    api.get<Connection[]>("/connections").then(setConnections);
  }

  useEffect(load, []);

  const githubConnections = connections.filter((c) => c.provider === "github");
  const googleCalendar = connections.find((c) => c.provider === "google_calendar");
  const gmail = connections.find((c) => c.provider === "gmail");
  const googleConnectedCount = [googleCalendar, gmail].filter(Boolean).length;

  const connectedBanner = searchParams.get("connected");
  const googleError = searchParams.get("google_error");

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

  async function handleConnectGoogle() {
    setGoogleConnecting(true);
    try {
      const { ticket } = await api.post<{ ticket: string }>("/integrations/google/connect-ticket");
      window.location.href = `${API_BASE}/integrations/google/connect?ticket=${encodeURIComponent(ticket)}`;
    } catch {
      setGoogleConnecting(false);
    }
  }

  async function handleDisconnectAllGoogle() {
    const ids = [googleCalendar?.id, gmail?.id].filter((id): id is string => Boolean(id));
    await Promise.all(ids.map((id) => api.delete(`/connections/${id}`)));
    load();
  }

  function toggleGroup(key: string) {
    setExpandedGroup(expandedGroup === key ? null : key);
  }

  return (
    <div className="max-w-2xl">
      <h1 className="mb-1 text-xl font-semibold text-balance">Agents &amp; Connections</h1>
      <p className="mb-7 text-[13px] text-ink-dim">
        Control what Sentinel watches and which agents are allowed to run.
      </p>

      {connectedBanner === "google" && (
        <Banner tone="good" onDismiss={() => setSearchParams({})}>
          Google connected — Calendar and Gmail will start syncing on the next run.
        </Banner>
      )}
      {googleError && (
        <Banner tone="crit" onDismiss={() => setSearchParams({})}>
          {GOOGLE_ERROR_MESSAGES[googleError] ?? "Couldn't connect Google — try again."}
        </Banner>
      )}

      <SectionLabel>Connections</SectionLabel>
      <div className="mb-8 flex flex-col gap-2.5">
        <ProviderGroupCard
          name="Google"
          summary={googleConnectedCount > 0 ? `${googleConnectedCount} service${googleConnectedCount === 1 ? "" : "s"} connected` : "Not connected"}
          connected={googleConnectedCount > 0}
          expanded={expandedGroup === "google"}
          onToggle={() => toggleGroup("google")}
        >
          <ServiceRow
            name="Gmail"
            desc="Subject, participants, timestamps — never message bodies"
            connected={Boolean(gmail)}
            detail={gmail?.org}
            onDisconnect={gmail ? () => handleDisconnect(gmail.id) : undefined}
          />
          <ServiceRow
            name="Google Calendar"
            desc="Meetings, attendees, duration"
            connected={Boolean(googleCalendar)}
            detail={googleCalendar?.org}
            onDisconnect={googleCalendar ? () => handleDisconnect(googleCalendar.id) : undefined}
          />
          <ServiceRow
            name="Google Meet"
            desc="Rides on Calendar — no separate connection needed"
            connected={googleConnectedCount > 0}
            disabled
          />
          <div className="flex items-center gap-3 border-t border-border p-3.5">
            <button
              onClick={handleConnectGoogle}
              disabled={googleConnecting}
              className="rounded-md bg-accent px-3.5 py-1.5 font-mono text-[11.5px] font-bold text-ground disabled:opacity-50"
            >
              {googleConnecting ? "Redirecting…" : googleConnectedCount > 0 ? "Reconnect Google" : "Connect Google"}
            </button>
            {googleConnectedCount > 0 && (
              <button
                onClick={handleDisconnectAllGoogle}
                className="font-mono text-[11.5px] text-crit underline underline-offset-2"
              >
                Disconnect all
              </button>
            )}
          </div>
        </ProviderGroupCard>

        <ProviderGroupCard
          name="GitHub"
          summary={githubConnections.length > 0 ? `${githubConnections.length} repo${githubConnections.length === 1 ? "" : "s"} connected` : "Not connected"}
          connected={githubConnections.length > 0}
          expanded={expandedGroup === "github"}
          onToggle={() => toggleGroup("github")}
        >
          {githubConnections.map((c) => (
            <ServiceRow
              key={c.id}
              name={`${c.org}/${c.repo}`}
              desc={c.last_synced_at ? `synced ${new Date(c.last_synced_at).toLocaleString()}` : "not yet synced"}
              connected
              mono
              onDisconnect={() => handleDisconnect(c.id)}
            />
          ))}

          <form onSubmit={handleConnect} className="border-t border-border p-3.5">
            <div className="mb-2.5 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
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
              className="mb-2.5 w-full rounded-md border border-border bg-ground px-3 py-2 text-[13px] outline-none focus:border-accent"
            />
            {error && <p className="mb-2 text-[12.5px] text-crit">{error}</p>}
            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-md bg-accent py-2 text-[12.5px] font-bold text-ground disabled:opacity-50"
            >
              {submitting ? "Connecting…" : "Connect repository"}
            </button>
            <p className="mt-2 text-[11.5px] text-ink-dim">
              🔒 PR, commit, issue, and review metadata only — never source code.
            </p>
          </form>
        </ProviderGroupCard>

        <ProviderGroupCard
          name="Zoom"
          summary="Coming soon"
          connected={false}
          disabled
          expanded={expandedGroup === "zoom"}
          onToggle={() => toggleGroup("zoom")}
        >
          <p className="p-3.5 text-[12.5px] text-ink-faint">Meeting metadata — not yet available.</p>
        </ProviderGroupCard>
      </div>

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

function ProviderGroupCard({
  name,
  summary,
  connected,
  expanded,
  onToggle,
  disabled,
  children,
}: {
  name: string;
  summary: string;
  connected: boolean;
  expanded: boolean;
  onToggle: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={`rounded-md border ${disabled ? "border-border/60 bg-surface/50" : "border-border bg-surface"}`}>
      <button onClick={onToggle} className="flex w-full items-center gap-3 p-3.5 text-left">
        <span className={`h-2 w-2 flex-none rounded-full ${connected ? "bg-good" : "bg-ink-faint"}`} />
        <div className="min-w-0 flex-1">
          <div className={`text-[13.5px] font-semibold ${disabled ? "text-ink-faint" : "text-ink"}`}>{name}</div>
          <div className="mt-0.5 text-[11.5px] text-ink-faint">{summary}</div>
        </div>
        <span className={`flex-none text-[12px] text-ink-faint transition-transform ${expanded ? "rotate-180" : ""}`}>
          &#9660;
        </span>
      </button>
      {expanded && <div className="border-t border-border">{children}</div>}
    </div>
  );
}

function ServiceRow({
  name,
  desc,
  connected,
  detail,
  disabled,
  mono,
  onDisconnect,
}: {
  name: string;
  desc: string;
  connected: boolean;
  detail?: string;
  disabled?: boolean;
  mono?: boolean;
  onDisconnect?: () => void;
}) {
  return (
    <div className="flex items-center gap-3 border-b border-border p-3.5 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className={`${mono ? "font-mono" : ""} text-[12.5px] font-semibold ${disabled ? "text-ink-faint" : "text-ink"}`}>
          {name}
        </div>
        <div className="mt-0.5 truncate text-[11px] text-ink-faint">{connected && detail ? detail : desc}</div>
      </div>
      <span
        className={`flex-none whitespace-nowrap rounded-full border px-2 py-[3px] text-[9.5px] font-medium uppercase tracking-wide ${
          connected ? "border-good/40 text-good" : "border-border text-ink-faint"
        }`}
      >
        {connected ? "Connected" : "Not connected"}
      </span>
      {onDisconnect && (
        <button
          onClick={onDisconnect}
          className="flex-none font-mono text-[11px] text-crit underline underline-offset-2"
        >
          Disconnect
        </button>
      )}
    </div>
  );
}

function Banner({ tone, children, onDismiss }: { tone: "good" | "crit"; children: ReactNode; onDismiss: () => void }) {
  return (
    <div className={`mb-5 flex items-center justify-between gap-3 border px-3.5 py-2.5 text-[12.5px] ${tone === "good" ? "border-good/40 bg-good/10 text-good" : "border-crit/40 bg-crit/10 text-crit"}`}>
      <span>{children}</span>
      <button onClick={onDismiss} className="flex-none opacity-70 hover:opacity-100">
        ✕
      </button>
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-2.5 font-mono text-[13px] font-bold uppercase tracking-wide text-ink-dim">{children}</div>
  );
}
