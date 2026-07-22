import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "../../api/client";
import type { ChannelConnection, ChannelReadiness, ChannelRequirement, Connection, AuthorizedConnection, ChannelExclusion } from "../../api/types";
import { PROVIDER_LABEL } from "../ChannelSetupChecklist";
import { LoadingBlock, useToast } from "../ui";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const REQUIREABLE_PROVIDERS = ["gmail", "google_calendar", "google_drive", "github"];

/**
 * Extensions is the channel's setup gateway.
 *
 * Two distinct things live here and are kept visually separate, because
 * confusing them is the failure mode:
 *
 *  - **Required integrations** - what an admin says this channel needs. A
 *    provider, never an account.
 *  - **Assigned connections** - which specific authorized accounts the
 *    channel's AI may read, and which resources within them.
 *
 * Nothing in this module lets an admin connect an account for someone else.
 */
export function ExtensionsModule({
  teamId,
  workspaceId,
  isAdmin,
  readiness,
  onChanged,
}: {
  teamId: string;
  workspaceId: string;
  isAdmin: boolean;
  readiness: ChannelReadiness | null;
  onChanged: () => void;
}) {
  const [requirements, setRequirements] = useState<ChannelRequirement[]>([]);
  const [connections, setConnections] = useState<ChannelConnection[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [reqs, conns] = await Promise.all([
        api.get<ChannelRequirement[]>(`/teams/${teamId}/requirements`),
        api.get<ChannelConnection[]>(`/teams/${teamId}/connections`),
      ]);
      setRequirements(reqs);
      setConnections(conns);
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingBlock />;

  const total = readiness?.requirements.filter((r) => r.is_required).length ?? 0;
  const ready = readiness?.requirements.filter((r) => r.is_required && r.state === "ready").length ?? 0;

  return (
    <div className="flex flex-col gap-6">
      {total > 0 && (
        <div className="card px-4 py-3">
          <div className="flex items-center justify-between">
            <span className="text-small font-semibold text-ink">Your channel setup</span>
            <span className={`font-mono text-caption ${ready === total ? "text-good" : "text-watch"}`}>
              {ready}/{total} complete
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
            <div
              className={`h-full rounded-full ${ready === total ? "bg-good" : "bg-watch"}`}
              style={{ width: `${total === 0 ? 0 : (ready / total) * 100}%` }}
            />
          </div>
        </div>
      )}

      <RequirementsSection
        teamId={teamId}
        isAdmin={isAdmin}
        requirements={requirements}
        onChanged={async () => {
          await load();
          onChanged();
        }}
      />

      <AssignedConnectionsSection
        teamId={teamId}
        workspaceId={workspaceId}
        isAdmin={isAdmin}
        connections={connections}
        onChanged={load}
      />

      {isAdmin && <RosterSection teamId={teamId} hasRequirements={requirements.length > 0} />}
    </div>
  );
}

function RequirementsSection({
  teamId,
  isAdmin,
  requirements,
  onChanged,
}: {
  teamId: string;
  isAdmin: boolean;
  requirements: ChannelRequirement[];
  onChanged: () => Promise<void>;
}) {
  const [provider, setProvider] = useState(REQUIREABLE_PROVIDERS[0]);
  const [reason, setReason] = useState("");
  const [required, setRequired] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/teams/${teamId}/requirements`, { provider, is_required: required, reason: reason.trim() || null });
      setReason("");
      await onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to add");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2 className="mb-1 text-body font-semibold text-ink">Required integrations</h2>
      <p className="mb-3 text-caption leading-relaxed text-ink-faint">
        What this channel needs. Each member connects their own account — an admin can never connect one on someone
        else's behalf.
      </p>

      {requirements.length === 0 ? (
        <p className="text-small text-ink-faint">
          None yet.{isAdmin ? " Add one below and every member will be prompted to connect their own account." : ""}
        </p>
      ) : (
        <div className="card-grid sm:grid-cols-2">
          {requirements.map((r) => (
            <div key={r.id} className="card">
              <div className="flex items-center justify-between">
                <span className="text-small font-semibold text-ink">{PROVIDER_LABEL[r.provider] ?? r.provider}</span>
                <div className="flex items-center gap-2">
                  <span className="label-sub">
                    {r.is_required ? "required" : "optional"}
                  </span>
                  {isAdmin && (
                    <button
                      onClick={async () => {
                        await api.delete(`/teams/${teamId}/requirements/${r.id}`);
                        await onChanged();
                      }}
                      className="text-caption text-ink-faint underline hover:text-crit"
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
              {r.reason && <p className="mt-1 text-caption text-ink-dim">{r.reason}</p>}
            </div>
          ))}
        </div>
      )}

      {isAdmin && (
        <div className="mt-3 rounded-md border border-dashed border-border px-5 py-8 text-center text-caption text-ink-faint">
          <div className="flex flex-wrap gap-1.5">
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              aria-label="Integration"
              className="rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {REQUIREABLE_PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {PROVIDER_LABEL[p]}
                </option>
              ))}
            </select>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why this channel needs it (shown to members)"
              className="min-w-[200px] flex-1 rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
            />
            <button
              onClick={add}
              disabled={busy}
              className="btn-primary"
            >
              Add
            </button>
          </div>
          <label className="mt-1.5 flex items-center gap-1.5 text-caption text-ink-dim">
            <input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} />
            Required (unchecked = suggested only, never blocks)
          </label>
          {error && <p className="mt-1 text-caption text-crit">{error}</p>}
        </div>
      )}
    </section>
  );
}

function AssignedConnectionsSection({
  teamId,
  workspaceId,
  isAdmin,
  connections,
  onChanged,
}: {
  teamId: string;
  workspaceId: string;
  isAdmin: boolean;
  connections: ChannelConnection[];
  onChanged: () => Promise<void>;
}) {
  const [available, setAvailable] = useState<Connection[]>([]);
  const [showPicker, setShowPicker] = useState(false);
  const [busy, setBusy] = useState(false);
  const [resourceForm, setResourceForm] = useState<Record<string, { key: string; label: string }>>({});

  useEffect(() => {
    if (!showPicker) return;
    api.get<Connection[]>("/connections", { workspaceId }).then(setAvailable).catch(() => setAvailable([]));
  }, [showPicker, workspaceId]);

  const assigned = new Set(connections.map((c) => c.connection_id));
  const assignable = available.filter((c) => !assigned.has(c.id));

  async function connectGoogleHere() {
    setBusy(true);
    try {
      const { ticket } = await api.post<{ ticket: string }>("/integrations/google/connect-ticket", undefined, {
        workspaceId,
      });
      const returnTo = encodeURIComponent(`/channels/${teamId}/extensions`);
      window.location.href = `${API_BASE}/integrations/google/connect?ticket=${encodeURIComponent(ticket)}&return_to=${returnTo}`;
    } catch {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2 className="mb-1 text-body font-semibold text-ink">What Sentinel can read here</h2>
      <p className="mb-3 text-caption leading-relaxed text-ink-faint">
        Connections assigned to this channel, and the specific resources authorized within them. Sentinel can use nothing
        else from the workspace.
      </p>

      <InheritedConnections teamId={teamId} isAdmin={isAdmin} />

      {connections.length === 0 && <p className="text-small text-ink-faint">Nothing assigned directly to this channel.</p>}

      <div className="flex flex-col gap-2">
        {connections.map((c) => (
          <div key={c.id} className="card">
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-small font-semibold text-ink">
                {PROVIDER_LABEL[c.provider] ?? c.provider} · {c.label}
              </span>
              {isAdmin && (
                <button
                  onClick={async () => {
                    if (
                      !window.confirm(
                        `Remove ${c.label} from this channel?\n\nSentinel will no longer be able to use it or any of its authorized resources here.`
                      )
                    )
                      return;
                    await api.delete(`/teams/${teamId}/connections/${c.id}`);
                    await onChanged();
                  }}
                  className="text-caption text-ink-faint underline hover:text-crit"
                >
                  Remove
                </button>
              )}
            </div>
            <div className="label-sub mb-1.5">
              Allow-listed resources
            </div>
            {c.resources.length === 0 ? (
              <p className="mb-1.5 text-caption text-ink-faint">
                None yet — nothing here is usable by Channel AI until a resource is added.
              </p>
            ) : (
              <div className="mb-1.5 flex flex-col gap-1">
                {c.resources.map((r) => (
                  <div key={r.id} className="flex items-center justify-between text-caption text-ink-dim">
                    <span className="truncate">{r.resource_label}</span>
                    {isAdmin && (
                      <button
                        onClick={async () => {
                          await api.delete(`/teams/${teamId}/connections/${c.id}/resources/${r.id}`);
                          await onChanged();
                        }}
                        className="text-micro text-ink-faint underline hover:text-crit"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
            {isAdmin && (
              <div className="flex gap-1.5">
                <input
                  value={resourceForm[c.id]?.key ?? ""}
                  onChange={(e) =>
                    setResourceForm((f) => ({ ...f, [c.id]: { key: e.target.value, label: f[c.id]?.label ?? "" } }))
                  }
                  placeholder="resource id/key"
                  className="w-1/2 rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
                />
                <input
                  value={resourceForm[c.id]?.label ?? ""}
                  onChange={(e) =>
                    setResourceForm((f) => ({ ...f, [c.id]: { key: f[c.id]?.key ?? "", label: e.target.value } }))
                  }
                  placeholder="display name"
                  className="w-1/2 rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
                />
                <button
                  onClick={async () => {
                    const form = resourceForm[c.id];
                    if (!form?.key.trim() || !form?.label.trim()) return;
                    await api.post(`/teams/${teamId}/connections/${c.id}/resources`, {
                      resource_key: form.key.trim(),
                      resource_label: form.label.trim(),
                    });
                    setResourceForm((f) => ({ ...f, [c.id]: { key: "", label: "" } }));
                    await onChanged();
                  }}
                  className="btn-primary flex-none"
                >
                  Add
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {isAdmin && (
        <div className="mt-2">
          {!showPicker ? (
            <button
              onClick={() => setShowPicker(true)}
              className="text-caption text-ink-faint underline hover:text-ink"
            >
              + Assign a connection
            </button>
          ) : (
            <div className="rounded-md border border-dashed border-border px-5 py-8 text-center text-caption text-ink-faint">
              <p className="mb-2 text-caption leading-relaxed text-ink-faint">
                Assigning a connection lets Sentinel use it here. It still can't read anything until you allow-list
                specific resources.
              </p>
              {assignable.length === 0 ? (
                <p className="mb-2 text-caption text-ink-faint">Everything in this workspace is already assigned here.</p>
              ) : (
                assignable.map((c) => (
                  <button
                    key={c.id}
                    onClick={async () => {
                      await api.post(`/teams/${teamId}/connections`, { connection_id: c.id });
                      setShowPicker(false);
                      await onChanged();
                    }}
                    className="block w-full rounded-md px-2 py-1.5 text-left text-caption text-ink-dim hover:bg-surface-2 hover:text-ink"
                  >
                    {c.provider} · {c.org}
                    {c.repo && c.provider === "github" ? `/${c.repo}` : ""}
                  </button>
                ))
              )}
              <div className="mt-2 border-t border-border pt-2">
                <button
                  onClick={connectGoogleHere}
                  disabled={busy}
                  className="block w-full rounded-md px-2 py-1.5 text-left text-caption text-ink-dim hover:bg-surface-2 hover:text-ink disabled:opacity-50"
                >
                  + Connect Google (Gmail, Calendar, Drive)
                </button>
                <Link
                  to="/connections/github"
                  className="block w-full rounded-md px-2 py-1.5 text-left text-caption text-ink-dim hover:bg-surface-2 hover:text-ink"
                >
                  + Connect GitHub
                </Link>
              </div>
              <button
                onClick={() => setShowPicker(false)}
                className="mt-1 text-caption text-ink-faint underline hover:text-ink"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function RosterSection({ teamId, hasRequirements }: { teamId: string; hasRequirements: boolean }) {
  const [roster, setRoster] = useState<import("../../api/types").MemberReadiness[]>([]);

  useEffect(() => {
    if (!hasRequirements) return;
    api
      .get<import("../../api/types").MemberReadiness[]>(`/teams/${teamId}/readiness/roster`)
      .then(setRoster)
      .catch(() => setRoster([]));
  }, [teamId, hasRequirements]);

  if (!hasRequirements || roster.length === 0) return null;

  return (
    <section>
      <h2 className="mb-1 text-body font-semibold text-ink">Member setup</h2>
      <p className="mb-3 text-caption text-ink-faint">
        Who still needs to connect. You see states, never anyone's credentials.
      </p>
      <div className="flex flex-col gap-1.5">
        {roster.map((m) => (
          <div key={m.user_id} className="flex items-start justify-between gap-2 text-small">
            <div className="min-w-0">
              <div className="truncate text-ink">{m.name ?? m.email}</div>
              <div className="truncate text-caption text-ink-faint">
                {m.requirements
                  .filter((r) => r.state !== "ready")
                  .map((r) => `${PROVIDER_LABEL[r.provider] ?? r.provider}: ${r.state.replace("_", " ")}`)
                  .join(" · ") || "all connected"}
              </div>
            </div>
            <span className={`flex-none font-mono text-micro ${m.is_ready ? "text-good" : "text-watch"}`}>
              {m.is_ready ? "ready" : "pending"}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}


/**
 * What this channel can actually read, and why - the three states an admin
 * has to be able to tell apart:
 *
 *   INHERITED  shared at the Workspace/Class/Group, flows down here
 *   EXCLUDED   inherited, but switched off for this channel only
 *   (channel-level assignments render in the section below this one)
 *
 * An admin can exclude an inherited connection without unsharing it from
 * anyone else, and lift that exclusion again. Everything else about an
 * inherited connection is managed where it was shared - this panel narrows,
 * it never grants.
 */
function InheritedConnections({ teamId, isAdmin }: { teamId: string; isAdmin: boolean }) {
  const [inherited, setInherited] = useState<AuthorizedConnection[]>([]);
  const [excluded, setExcluded] = useState<ChannelExclusion[]>([]);
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  const load = useCallback(async () => {
    try {
      const [all, ex] = await Promise.all([
        api.get<AuthorizedConnection[]>(`/teams/${teamId}/authorized-connections`),
        api.get<ChannelExclusion[]>(`/teams/${teamId}/exclusions`),
      ]);
      setInherited(all.filter((c) => c.source !== "channel"));
      setExcluded(ex);
    } catch {
      setInherited([]);
      setExcluded([]);
    }
  }, [teamId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (inherited.length === 0 && excluded.length === 0) return null;

  async function exclude(connectionId: string) {
    setBusy(true);
    try {
      await api.post(`/teams/${teamId}/exclusions`, { connection_id: connectionId });
      await load();
      toast("Excluded from this channel only", "success");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Failed to exclude", "error");
    } finally {
      setBusy(false);
    }
  }

  async function lift(exclusionId: string) {
    setBusy(true);
    try {
      await api.delete(`/teams/${teamId}/exclusions/${exclusionId}`);
      await load();
      toast("Access restored — inheriting again", "success");
    } catch (e) {
      toast(e instanceof ApiError ? e.message : "Failed to restore", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-4 rounded-md border border-brand/25 bg-brand/[0.04] p-3.5">
      <div className="label-sub mb-1 text-brand">Inherited shared context</div>
      <p className="mb-2.5 text-micro leading-relaxed text-ink-faint">
        Shared by an admin above this channel. Managed where it was shared — here you can only switch it off for this
        channel.
      </p>

      <div className="flex flex-col gap-1.5">
        {inherited.map((c) => (
          <div key={c.connection_id} className="flex items-center justify-between gap-3 text-caption">
            <span className="min-w-0 truncate text-ink-dim">
              {PROVIDER_LABEL[c.provider] ?? c.provider} · {c.label}
              {c.resources.length > 0 && (
                <span className="text-ink-faint">
                  {" "}
                  · {c.resources.length} resource{c.resources.length === 1 ? "" : "s"}
                </span>
              )}
            </span>
            <span className="flex flex-none items-center gap-2">
              <span className="rounded-full border border-brand/30 px-2 py-px text-micro text-brand">
                from {c.source}
              </span>
              {isAdmin && (
                <button
                  onClick={() => exclude(c.connection_id)}
                  disabled={busy}
                  className="text-micro text-ink-faint underline underline-offset-2 hover:text-crit disabled:opacity-50"
                >
                  Exclude
                </button>
              )}
            </span>
          </div>
        ))}

        {excluded.map((e) => (
          <div key={e.id} className="flex items-center justify-between gap-3 text-caption">
            <span className="min-w-0 truncate text-ink-faint line-through">
              {PROVIDER_LABEL[e.provider] ?? e.provider} · {e.label}
            </span>
            <span className="flex flex-none items-center gap-2">
              <span className="rounded-full border border-crit/30 bg-crit/10 px-2 py-px text-micro text-crit">
                excluded here
              </span>
              {isAdmin && (
                <button
                  onClick={() => lift(e.id)}
                  disabled={busy}
                  className="text-micro text-ink-faint underline underline-offset-2 hover:text-ink disabled:opacity-50"
                >
                  Restore
                </button>
              )}
            </span>
          </div>
        ))}
      </div>

      {excluded.length > 0 && (
        <p className="mt-2 text-micro leading-relaxed text-ink-faint">
          An exclusion blocks the connection <span className="text-ink-dim">in this channel only</span> — other channels
          keep inheriting it normally.
        </p>
      )}
    </div>
  );
}
