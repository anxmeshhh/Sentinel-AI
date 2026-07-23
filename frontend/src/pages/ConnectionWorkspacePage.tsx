import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { Connection, GitHubRepo, GitHubRepository } from "../api/types";
import { BackNav } from "../components/BackNav";
import { ConnectScopeDialog } from "../components/ConnectScopeDialog";
import { SentinelPanel } from "../components/SentinelPanel";
import { workspaceContext } from "../components/context";
import { ScopeNotice, scopeOf } from "../components/ScopeBadge";
import { useWorkspace } from "../context/WorkspaceContext";
import { CalendarIcon, DriveIcon, GitHubIcon, GoogleIcon, MailIcon, MeetIcon, NotionIcon, SlackIcon, ZoomIcon } from "../components/ProviderIcons";
import { ServiceCard } from "../components/ServiceCard";
import { Icon, LoadingBlock } from "../components/ui";

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

  // The AI panel only exists where the orchestrator actually has tools -
  // Google today. Showing it on GitHub/coming-soon pages would promise an
  // intelligence that isn't wired up yet.
  const showPanel = meta != null && provider === "google" && !loading && connections.length > 0;

  return (
    <div className="flex flex-col gap-6 xl:flex-row">
      <div className="min-w-0 max-w-3xl flex-1">
        <BackNav back={{ to: "/", label: "Dashboard" }} crumbs={meta ? [{ label: "Dashboard", to: "/" }, { label: "Connections", to: "/" }, { label: meta.label }] : undefined} />

        {!meta ? (
          <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
            Unknown connection.
          </div>
        ) : (
          <>
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-md bg-surface-2">{meta.icon}</div>
              <h1 className="text-h2 font-medium text-balance">{meta.label}</h1>
            </div>

            {/* Who can use anything connected here - stated up front, not
                hidden behind settings or a tooltip. */}
            <ScopeNotice scope={scopeOf(active)} workspaceName={active?.name} />

            {loading ? (
              <LoadingBlock />
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

      {showPanel && <AISidebar />}
    </div>
  );
}

/** The persistent Sentinel panel: main area is where you work manually,
 *  this is where you ask for help with whatever you're looking at.
 *  Collapsible so the main workspace can take the full width. */
function AISidebar() {
  const { active } = useWorkspace();
  const [open, setOpen] = useState(true);

  if (!open) {
    return (
      <div className="flex-none xl:w-10">
        <button
          onClick={() => setOpen(true)}
          title="Open Sentinel"
          className="xl:sticky xl:top-6 flex items-center gap-2 rounded-md border border-border px-3 py-2 text-caption text-ink-dim transition-colors hover:border-border-strong hover:text-ink"
        >
          <span className="relative h-[14px] w-[14px] flex-none rounded-full border border-ink" aria-hidden="true">
            <span className="absolute inset-[4px] rounded-full bg-brand" />
          </span>
          <span className="xl:hidden">Sentinel</span>
        </button>
      </div>
    );
  }

  return (
    <aside className="w-full flex-none xl:w-[380px]">
      <div className="card overflow-hidden p-0 sm:p-0 xl:sticky xl:top-6 xl:h-[calc(100vh-6rem)]" style={{ minHeight: 420 }}>
        <SentinelPanel
          contextLabel="Google Workspace"
          identity={workspaceContext(active)}
          suggestions={[
            "What are my most important unread emails?",
            "What's on my calendar this week?",
            "Find my most recently edited Drive files",
          ]}
          header={
            <button onClick={() => setOpen(false)} aria-label="Collapse Sentinel" className="rounded-md p-1 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink">
              <Icon name="close" size={14} />
            </button>
          }
        />
      </div>
    </aside>
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
      <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
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
          desc="Rides on Calendar — no separate connection"
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

/**
 * GitHub, connected by OAuth.
 *
 * Replaces a personal-access-token form that had been failing since
 * connections became per-user: it never sent an owner, so every submission
 * hit a NOT NULL constraint. Nobody could have connected GitHub through it.
 *
 * The flow is two steps on purpose. One token can read many repositories and
 * Sentinel watches one, so authorizing does not by itself say which - and
 * picking for the user would quietly sync the wrong thing. The second step
 * offers exactly the repositories the granted scopes can actually read, so a
 * choice made here is known to work rather than typed and hoped for.
 */
const REPO_STATE: Record<string, { label: string; tone: string }> = {
  ready: { label: "Watching", tone: "text-good" },
  syncing: { label: "Syncing…", tone: "text-watch" },
  error: { label: "Sync failing", tone: "text-crit" },
  paused: { label: "Paused", tone: "text-ink-faint" },
  token_revoked: { label: "Reconnect needed", tone: "text-crit" },
  needs_setup: { label: "Not set up", tone: "text-watch" },
};

/**
 * GitHub as a multi-repository provider.
 *
 * One account, several watched repositories - each its own connection, so
 * each can be paused, synced or removed on its own. The page has two halves:
 * what Sentinel is watching (with per-repo health and controls), and the
 * repositories the account could add. When the account is not connected at
 * all, only the connect prompt shows.
 */
function GitHubWorkspace({ connections, onChanged }: { connections: Connection[]; onChanged: () => void }) {
  // The account is "connected" if any GitHub connection row exists - watched
  // or an anchor. connections here only carries watched repos (repo set), so
  // we probe the management endpoint to learn the true account state.
  const [watching, setWatching] = useState<GitHubRepository[]>([]);
  const [available, setAvailable] = useState<GitHubRepo[]>([]);
  const [accountConnected, setAccountConnected] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [adding, setAdding] = useState(false);

  const hasGitHub = connections.some((c) => c.provider === "github");

  const load = useCallback(async () => {
    try {
      const repos = await api.get<GitHubRepository[]>("/integrations/github/repositories");
      setWatching(repos);
      setAccountConnected(true);
    } catch (e) {
      // 404 means no GitHub account at all; anything else is a real error.
      if (e instanceof ApiError && e.status === 404) setAccountConnected(false);
      else setError(e instanceof ApiError ? e.message : "Couldn't load your repositories");
    }
  }, []);

  useEffect(() => {
    if (hasGitHub) void load();
    else setAccountConnected(false);
  }, [hasGitHub, load]);

  async function loadAvailable() {
    setAdding(true);
    setError(null);
    try {
      setAvailable(await api.get<GitHubRepo[]>("/integrations/github/repos"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load your repositories");
      setAdding(false);
    }
  }

  async function connect() {
    setBusy("connect");
    setError(null);
    try {
      const { ticket } = await api.post<{ ticket: string }>("/integrations/github/connect-ticket");
      const returnTo = encodeURIComponent("/connections/github");
      window.location.href = `${API_BASE}/integrations/github/connect?ticket=${encodeURIComponent(ticket)}&return_to=${returnTo}`;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start the GitHub connection");
      setBusy(null);
    }
  }

  async function addRepo(org: string, repo: string) {
    setBusy(`${org}/${repo}`);
    setError(null);
    try {
      await api.post("/integrations/github/repositories", { org, repo });
      setAdding(false);
      setFilter("");
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't add that repository");
    } finally {
      setBusy(null);
    }
  }

  async function repoAction(id: string, verb: "pause" | "resume" | "sync" | "remove") {
    setBusy(id);
    setError(null);
    try {
      if (verb === "remove") await api.delete(`/integrations/github/repositories/${id}`);
      else await api.post(`/integrations/github/repositories/${id}/${verb}`);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That didn't work");
    } finally {
      setBusy(null);
    }
  }

  const watchedKeys = new Set(watching.map((r) => r.full_name.toLowerCase()));
  const addable = available.filter(
    (r) => !watchedKeys.has(r.full_name.toLowerCase()) &&
      (!filter || r.full_name.toLowerCase().includes(filter.toLowerCase())),
  );

  if (accountConnected === null) return <LoadingBlock />;

  if (!accountConnected) {
    return (
      <div>
        {error && <p className="mb-3 text-small text-crit">{error}</p>}
        <div className="card p-4">
          <div className="mb-1 text-body font-semibold text-ink">Connect your GitHub account</div>
          <p className="mb-3 text-small leading-relaxed text-ink-dim">
            You'll authorize Sentinel on GitHub, then choose which repositories to watch. Sentinel reads pull request,
            commit, issue and review <span className="text-ink">metadata only</span> — never source code, diffs or file
            contents.
          </p>
          <button onClick={connect} disabled={busy === "connect"} className="btn-primary">
            {busy === "connect" ? "Redirecting…" : "Connect GitHub"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      {error && <p className="mb-3 text-small text-crit">{error}</p>}

      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-body font-semibold text-ink">
          Watching {watching.length} {watching.length === 1 ? "repository" : "repositories"}
        </div>
        <div className="flex items-center gap-3 text-caption">
          <button
            onClick={() => (adding ? setAdding(false) : loadAvailable())}
            className="text-ink-faint underline underline-offset-2 hover:text-ink"
          >
            {adding ? "Done adding" : "+ Add repository"}
          </button>
          <button onClick={connect} className="text-ink-faint underline underline-offset-2 hover:text-ink">
            Reconnect
          </button>
        </div>
      </div>

      {watching.length === 0 && !adding && (
        <p className="mb-3 text-small text-ink-dim">
          No repositories yet. <button onClick={loadAvailable} className="text-accent-text hover:underline">Add one</button> to start watching it.
        </p>
      )}

      <div className="mb-4 flex flex-col gap-2">
        {watching.map((r) => {
          const state = REPO_STATE[r.state] ?? REPO_STATE.ready;
          return (
            <div key={r.connection_id} className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface p-3">
              <div className="min-w-0">
                <div className="truncate text-small font-semibold text-ink">{r.full_name}</div>
                <div className="mt-0.5 flex flex-wrap items-center gap-2 text-micro text-ink-faint">
                  <span className={`font-mono uppercase tracking-wide ${state.tone}`}>{state.label}</span>
                  <span>· {r.signal_count} signal{r.signal_count === 1 ? "" : "s"}</span>
                  <span>· {r.last_success_at ? `synced ${new Date(r.last_success_at).toLocaleDateString()}` : "not yet synced"}</span>
                </div>
              </div>
              <div className="flex flex-none items-center gap-2.5 text-caption">
                {r.state !== "paused" && (
                  <button onClick={() => repoAction(r.connection_id, "sync")} disabled={busy === r.connection_id} className="text-ink-faint underline underline-offset-2 hover:text-ink disabled:opacity-50">
                    Sync now
                  </button>
                )}
                <button onClick={() => repoAction(r.connection_id, r.paused ? "resume" : "pause")} disabled={busy === r.connection_id} className="text-ink-faint underline underline-offset-2 hover:text-ink disabled:opacity-50">
                  {r.paused ? "Resume" : "Pause"}
                </button>
                <button onClick={() => repoAction(r.connection_id, "remove")} disabled={busy === r.connection_id} className="text-ink-faint underline underline-offset-2 hover:text-crit disabled:opacity-50">
                  Remove
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {adding && (
        <div className="card p-4">
          <div className="mb-2 text-body font-semibold text-ink">Add a repository</div>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={`Filter ${available.length} readable repositories…`}
            className="mb-2 w-full rounded-md border border-border bg-transparent px-3 py-2 text-small outline-none focus:border-border-strong"
          />
          {addable.length === 0 ? (
            <p className="text-small text-ink-dim">
              {available.length === 0 ? "No repositories are readable with the access you granted." : "Nothing else to add — everything matching is already watched."}
            </p>
          ) : (
            <div className="flex max-h-72 flex-col gap-1 overflow-y-auto">
              {addable.map((r) => (
                <button
                  key={r.full_name}
                  onClick={() => addRepo(r.org, r.repo)}
                  disabled={busy === `${r.org}/${r.repo}`}
                  className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left text-small text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-50"
                >
                  <span className="min-w-0 truncate">{r.full_name}</span>
                  <span className="flex-none text-micro text-ink-faint">
                    {r.private ? "private" : "public"}{r.pushed_at ? ` · ${new Date(r.pushed_at).toLocaleDateString()}` : ""}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <p className="mt-3 text-caption text-ink-dim">
        🔒 PR, commit, issue and review metadata only — never source code.
      </p>
    </div>
  );
}

function ComingSoonWorkspace({ label }: { label: string }) {
  return (
    <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
      {label} isn't available yet — check back soon.
    </div>
  );
}
