import type { FormEvent, ReactNode } from "react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Connection } from "../api/types";
import { GoogleAICommand } from "./GoogleAICommand";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type ProviderKey = "google" | "github" | "zoom" | "slack" | "notion";

export function IntegrationCardGrid({ connections, onChanged }: { connections: Connection[]; onChanged: () => void }) {
  const [selected, setSelected] = useState<ProviderKey>("google");

  const githubConnections = connections.filter((c) => c.provider === "github");
  const googleCalendar = connections.find((c) => c.provider === "google_calendar");
  const gmail = connections.find((c) => c.provider === "gmail");
  const googleConnectedCount = [googleCalendar, gmail].filter(Boolean).length;

  return (
    <div className="mb-8">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <IntegrationCard
          icon={<GoogleIcon />}
          name="Google"
          status={googleConnectedCount > 0 ? `${googleConnectedCount} service${googleConnectedCount === 1 ? "" : "s"} connected` : "Not connected"}
          desc="Gmail, Calendar, Meet — the main module: browse, ask, and get risk findings from your inbox and calendar."
          connected={googleConnectedCount > 0}
          active={selected === "google"}
          onClick={() => setSelected("google")}
        />
        <IntegrationCard
          icon={<GitHubIcon />}
          name="GitHub"
          status={githubConnections.length > 0 ? `${githubConnections.length} repo${githubConnections.length === 1 ? "" : "s"} connected` : "Not connected"}
          desc="PRs, commits, issues, reviews — bottlenecks, hotspots, risky deploys."
          connected={githubConnections.length > 0}
          active={selected === "github"}
          onClick={() => setSelected("github")}
        />
        <IntegrationCard
          icon={<ZoomIcon />}
          name="Zoom"
          status="Coming soon"
          desc="Meeting metadata — not yet available."
          connected={false}
          disabled
          active={selected === "zoom"}
          onClick={() => setSelected("zoom")}
        />
        <IntegrationCard
          icon={<SlackIcon />}
          name="Slack"
          status="Coming soon"
          desc="Gaps, unanswered questions, missing approvals — not yet available."
          connected={false}
          disabled
          active={selected === "slack"}
          onClick={() => setSelected("slack")}
        />
        <IntegrationCard
          icon={<NotionIcon />}
          name="Notion"
          status="Coming soon"
          desc="Stale or missing docs — not yet available."
          connected={false}
          disabled
          active={selected === "notion"}
          onClick={() => setSelected("notion")}
        />
      </div>

      <div className="mt-3 rounded-md border border-border bg-surface">
        {selected === "google" && (
          <GoogleDetail googleCalendar={googleCalendar} gmail={gmail} onChanged={onChanged} />
        )}
        {selected === "github" && <GitHubDetail connections={githubConnections} onChanged={onChanged} />}
        {selected === "zoom" && <p className="p-4 text-[12.5px] text-ink-faint">Meeting metadata — not yet available.</p>}
        {selected === "slack" && <p className="p-4 text-[12.5px] text-ink-faint">Gaps, unanswered questions, missing approvals — not yet available.</p>}
        {selected === "notion" && <p className="p-4 text-[12.5px] text-ink-faint">Stale or missing docs — not yet available.</p>}
      </div>
    </div>
  );
}

function IntegrationCard({
  icon,
  name,
  status,
  desc,
  connected,
  active,
  disabled,
  onClick,
}: {
  icon: ReactNode;
  name: string;
  status: string;
  desc: string;
  connected: boolean;
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg border p-5 text-left transition-colors ${
        active ? "border-accent bg-accent/5" : "border-border bg-surface hover:border-accent/50"
      } ${disabled ? "opacity-70" : ""}`}
    >
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-md bg-surface-2">{icon}</div>
      <div className="mb-1 text-[14px] font-semibold text-ink">{name}</div>
      <div className={`mb-2 text-[12.5px] font-semibold ${connected ? "text-good" : "text-ink-faint"}`}>{status}</div>
      <div className="text-[11.5px] leading-relaxed text-ink-faint">{desc}</div>
    </button>
  );
}

function GoogleDetail({
  googleCalendar,
  gmail,
  onChanged,
}: {
  googleCalendar: Connection | undefined;
  gmail: Connection | undefined;
  onChanged: () => void;
}) {
  const [connecting, setConnecting] = useState(false);
  const connectedCount = [googleCalendar, gmail].filter(Boolean).length;

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
    const ids = [googleCalendar?.id, gmail?.id].filter((id): id is string => Boolean(id));
    await Promise.all(ids.map((id) => api.delete(`/connections/${id}`)));
    onChanged();
  }

  return (
    <>
      <ServiceRow
        name="Gmail"
        desc="Subject, participants, timestamps — never message bodies"
        connected={Boolean(gmail)}
        detail={gmail?.org}
        href={gmail ? "/mail" : undefined}
        onDisconnect={gmail ? () => handleDisconnect(gmail.id) : undefined}
      />
      <ServiceRow
        name="Google Calendar"
        desc="Meetings, attendees, duration"
        connected={Boolean(googleCalendar)}
        detail={googleCalendar?.org}
        href={googleCalendar ? "/calendar" : undefined}
        onDisconnect={googleCalendar ? () => handleDisconnect(googleCalendar.id) : undefined}
      />
      <ServiceRow name="Google Meet" desc="Rides on Calendar — no separate connection needed" connected={connectedCount > 0} disabled />
      <div className="flex items-center gap-3 p-3.5">
        <button
          onClick={handleConnect}
          disabled={connecting}
          className="rounded-md bg-accent px-3.5 py-1.5 font-mono text-[11.5px] font-bold text-ground disabled:opacity-50"
        >
          {connecting ? "Redirecting…" : connectedCount > 0 ? "Reconnect Google" : "Connect Google"}
        </button>
        {connectedCount > 0 && (
          <button onClick={handleDisconnectAll} className="font-mono text-[11.5px] text-crit underline underline-offset-2">
            Disconnect all
          </button>
        )}
      </div>
      {connectedCount > 0 && <GoogleAICommand />}
    </>
  );
}

function GitHubDetail({ connections, onChanged }: { connections: Connection[]; onChanged: () => void }) {
  const [org, setOrg] = useState("");
  const [repo, setRepo] = useState("");
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConnect(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/connections", { org, repo, github_token: token });
      setOrg("");
      setRepo("");
      setToken("");
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to connect repository");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDisconnect(id: string) {
    await api.delete(`/connections/${id}`);
    onChanged();
  }

  return (
    <>
      {connections.map((c) => (
        <ServiceRow
          key={c.id}
          name={`${c.org}/${c.repo}`}
          desc={c.last_synced_at ? `synced ${new Date(c.last_synced_at).toLocaleString()}` : "not yet synced"}
          connected
          mono
          onDisconnect={() => handleDisconnect(c.id)}
        />
      ))}
      <form onSubmit={handleConnect} className="p-3.5">
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
          className="w-full rounded-md bg-accent py-2 text-[12.5px] font-bold text-ground disabled:opacity-50 sm:w-auto sm:px-4"
        >
          {submitting ? "Connecting…" : "Connect repository"}
        </button>
        <p className="mt-2 text-[11.5px] text-ink-dim">🔒 PR, commit, issue, and review metadata only — never source code.</p>
      </form>
    </>
  );
}

function ServiceRow({
  name,
  desc,
  connected,
  detail,
  disabled,
  mono,
  href,
  onDisconnect,
}: {
  name: string;
  desc: string;
  connected: boolean;
  detail?: string;
  disabled?: boolean;
  mono?: boolean;
  href?: string;
  onDisconnect?: () => void;
}) {
  return (
    <div className="flex items-center gap-3 border-b border-border p-3.5 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className={`${mono ? "font-mono" : ""} text-[12.5px] font-semibold ${disabled ? "text-ink-faint" : "text-ink"}`}>
          {href ? (
            <Link to={href} className="hover:underline hover:underline-offset-2">
              {name}
            </Link>
          ) : (
            name
          )}
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
      {href && (
        <Link to={href} className="flex-none font-mono text-[11px] text-ink-dim underline underline-offset-2 hover:text-ink">
          Open
        </Link>
      )}
      {onDisconnect && (
        <button onClick={onDisconnect} className="flex-none font-mono text-[11px] text-crit underline underline-offset-2">
          Disconnect
        </button>
      )}
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.99.66-2.25 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.85A11 11 0 0 0 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.09A6.6 6.6 0 0 1 5.5 12c0-.73.13-1.43.34-2.09V7.06H2.18A11 11 0 0 0 1 12c0 1.77.43 3.45 1.18 4.94l3.66-2.85z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1a11 11 0 0 0-9.82 6.06l3.66 2.85C6.71 7.31 9.14 5.38 12 5.38z" />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" className="text-ink" aria-hidden="true">
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.57.1.78-.25.78-.55v-2.1c-3.2.7-3.87-1.36-3.87-1.36-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.7.08-.7 1.17.08 1.78 1.2 1.78 1.2 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.04 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.79 0c2.2-1.49 3.17-1.18 3.17-1.18.64 1.58.24 2.75.12 3.04.74.81 1.19 1.83 1.19 3.09 0 4.42-2.7 5.4-5.26 5.68.42.36.78 1.07.78 2.16v3.2c0 .31.21.66.79.55A10.52 10.52 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5z" />
    </svg>
  );
}

function ZoomIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="1" y="4" width="16" height="16" rx="4" fill="#2D8CFF" opacity="0.5" />
      <path d="M18 9.5l4.5-2.7a.6.6 0 0 1 .9.5v9.4a.6.6 0 0 1-.9.5L18 14.5v-5z" fill="#2D8CFF" opacity="0.5" />
    </svg>
  );
}

function SlackIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" opacity="0.5">
      <rect x="9" y="1" width="4" height="9" rx="2" fill="#36C5F0" />
      <rect x="14" y="9" width="9" height="4" rx="2" fill="#2EB67D" />
      <rect x="11" y="14" width="4" height="9" rx="2" fill="#ECB22E" />
      <rect x="1" y="11" width="9" height="4" rx="2" fill="#E01E5A" />
    </svg>
  );
}

function NotionIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" className="text-ink opacity-50" aria-hidden="true">
      <path d="M4 3.5A1.5 1.5 0 0 1 5.5 2h13A1.5 1.5 0 0 1 20 3.5v17a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 20.5v-17zM8 8v9h1.6V10.7L14 17h1.6V8H14v6.3L9.6 8H8z" />
    </svg>
  );
}
