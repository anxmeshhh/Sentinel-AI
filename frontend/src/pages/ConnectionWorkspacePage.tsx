import type { FormEvent, ReactNode } from "react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Connection } from "../api/types";
import { BackNav } from "../components/BackNav";
import { ConnectScopeDialog } from "../components/ConnectScopeDialog";
import { GoogleAICommand } from "../components/GoogleAICommand";
import { ScopeNotice, scopeOf } from "../components/ScopeBadge";
import { useWorkspace } from "../context/WorkspaceContext";
import { CalendarIcon, DriveIcon, GitHubIcon, GoogleIcon, MailIcon, MeetIcon, NotionIcon, SlackIcon, ZoomIcon } from "../components/ProviderIcons";
import { ServiceCard } from "../components/ServiceCard";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const PROVIDER_META: Record<string, { label: string; icon: ReactNode }> = {
  google: { label: "Google", icon: <GoogleIcon /> },
  github: { label: "GitHub", icon: <GitHubIcon /> },
  zoom: { label: "Zoom", icon: <ZoomIcon /> },
  slack: { label: "Slack", icon: <SlackIcon /> },
  notion: { label: "Notion", icon: <NotionIcon /> },
};

export function ConnectionWorkspacePage() {
  const { provider = "" } = useParams<{ provider: string }>();
  const { active } = useWorkspace();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    api
      .get<Connection[]>("/connections")
      .then(setConnections)
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  const meta = PROVIDER_META[provider];

  return (
    <div className="max-w-3xl">
      <BackNav back={{ to: "/", label: "Dashboard" }} crumbs={meta ? [{ label: "Dashboard", to: "/" }, { label: "Connections", to: "/" }, { label: meta.label }] : undefined} />

      {!meta ? (
        <div className="rounded-md border border-dashed border-border-strong p-8 text-center text-body text-ink-faint">
          Unknown connection.
        </div>
      ) : (
        <>
          <div className="mb-4 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-md bg-surface-2">{meta.icon}</div>
            <h1 className="text-h2 font-semibold text-balance">{meta.label}</h1>
          </div>

          {/* Who can use anything connected here - stated up front, not
              hidden behind settings or a tooltip. */}
          <ScopeNotice scope={scopeOf(active)} workspaceName={active?.name} />

          {loading ? (
            <div className="text-ink-dim">Loading&hellip;</div>
          ) : provider === "google" ? (
            <GoogleWorkspace connections={connections} onChanged={load} />
          ) : provider === "github" ? (
            <GitHubWorkspace connections={connections} onChanged={load} />
          ) : (
            <ComingSoonWorkspace label={meta.label} />
          )}
        </>
      )}
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

  return (
    <div>
      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <ServiceCard
          icon={<MailIcon />}
          name="Gmail"
          status={gmail ? "Connected" : "Not connected"}
          desc={gmail?.org ?? "Subject, participants, timestamps — never message bodies"}
          connected={Boolean(gmail)}
          to={gmail ? "/mail" : undefined}
          disabled={!gmail}
        />
        <ServiceCard
          icon={<CalendarIcon />}
          name="Google Calendar"
          status={googleCalendar ? "Connected" : "Not connected"}
          desc={googleCalendar?.org ?? "Meetings, attendees, duration"}
          connected={Boolean(googleCalendar)}
          to={googleCalendar ? "/calendar" : undefined}
          disabled={!googleCalendar}
        />
        <ServiceCard
          icon={<MeetIcon />}
          name="Google Meet"
          status={googleCalendar ? "Available" : "Not connected"}
          desc="Meeting history — rides on Calendar, no separate connection needed"
          connected={Boolean(googleCalendar)}
          to={googleCalendar ? "/meet" : undefined}
          disabled={!googleCalendar}
        />
        <ServiceCard
          icon={<DriveIcon />}
          name="Google Drive"
          status={googleDrive ? "Connected" : "Not connected"}
          desc={googleDrive?.org ?? "File name, type, modified time — never file content"}
          connected={Boolean(googleDrive)}
          to={googleDrive ? "/drive" : undefined}
          disabled={!googleDrive}
        />
      </div>

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <button
          onClick={() => setShowScopeDialog(true)}
          disabled={connecting}
          className="btn-primary"
        >
          {connecting ? "Redirecting…" : connectedCount > 0 ? "Reconnect Google" : "Connect Google"}
        </button>
        {gmail && (
          <button onClick={() => handleDisconnect(gmail.id)} className="text-caption text-ink-faint underline underline-offset-2 hover:text-crit">
            Disconnect Gmail
          </button>
        )}
        {googleCalendar && (
          <button onClick={() => handleDisconnect(googleCalendar.id)} className="text-caption text-ink-faint underline underline-offset-2 hover:text-crit">
            Disconnect Calendar
          </button>
        )}
        {googleDrive && (
          <button onClick={() => handleDisconnect(googleDrive.id)} className="text-caption text-ink-faint underline underline-offset-2 hover:text-crit">
            Disconnect Drive
          </button>
        )}
        {connectedCount > 0 && (
          <button onClick={handleDisconnectAll} className="text-caption text-crit underline underline-offset-2">
            Disconnect all
          </button>
        )}
      </div>

      {googleDrive === undefined && (gmail || googleCalendar) && (
        <p className="mb-4 text-small text-watch">
          Drive needs the newer Google connection scope — click "Reconnect Google" above to add it.
        </p>
      )}

      {connectedCount > 0 && (
        <div className="rounded-lg border border-border bg-surface shadow-card">
          <GoogleAICommand />
        </div>
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

function GitHubWorkspace({ connections, onChanged }: { connections: Connection[]; onChanged: () => void }) {
  const repos = connections.filter((c) => c.provider === "github");
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
    <div>
      {repos.length > 0 && (
        <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {repos.map((c) => (
            <ServiceCard
              key={c.id}
              icon={<GitHubIcon />}
              name={`${c.org}/${c.repo}`}
              status="Connected"
              desc={c.last_synced_at ? `synced ${new Date(c.last_synced_at).toLocaleString()}` : "not yet synced"}
              connected
              onRemove={() => handleDisconnect(c.id)}
            />
          ))}
        </div>
      )}

      <form onSubmit={handleConnect} className="rounded-lg border border-border bg-surface shadow-card p-4">
        <div className="mb-2.5 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <input
            required
            placeholder="org (e.g. northwind)"
            value={org}
            onChange={(e) => setOrg(e.target.value)}
            className="rounded-md border border-border bg-ground px-3 py-2 text-body outline-none focus:border-accent focus:ring-2 focus:ring-accent/25"
          />
          <input
            required
            placeholder="repo (e.g. checkout-service)"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            className="rounded-md border border-border bg-ground px-3 py-2 text-body outline-none focus:border-accent focus:ring-2 focus:ring-accent/25"
          />
        </div>
        <input
          required
          type="password"
          placeholder="GitHub personal access token"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="mb-2.5 w-full rounded-md border border-border bg-ground px-3 py-2 text-body outline-none focus:border-accent focus:ring-2 focus:ring-accent/25"
        />
        {error && <p className="mb-2 text-small text-crit">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="btn-primary"
        >
          {submitting ? "Connecting…" : "Connect repository"}
        </button>
        <p className="mt-2 text-caption text-ink-dim">🔒 PR, commit, issue, and review metadata only — never source code.</p>
      </form>
    </div>
  );
}

function ComingSoonWorkspace({ label }: { label: string }) {
  return (
    <div className="rounded-md border border-dashed border-border-strong p-8 text-center text-body text-ink-faint">
      {label} isn't available yet — check back soon.
    </div>
  );
}
