import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api/client";
import type { Connection, SharedConnection } from "../api/types";
import { PROVIDER_LABEL } from "./ChannelSetupChecklist";
import { Modal } from "./Modal";
import { Button, LoadingBlock } from "./ui";

/**
 * Manage the connections shared at one Class or Group.
 *
 * A connection shared here becomes context for every Channel beneath this
 * scope - assign the class repo once, all its channels inherit it. Same
 * fail-closed resource model as a channel: a Drive connection grants no file
 * until a resource is allow-listed.
 *
 * One modal serves both tiers; only the base path differs, so Class and
 * Group management can't drift into two different experiences.
 */
export function SharedConnectionsModal({
  scope,
  workspaceId,
  classId,
  groupId,
  label,
  onClose,
}: {
  scope: "class" | "group";
  workspaceId: string;
  classId: string;
  groupId?: string;
  label: string;
  onClose: () => void;
}) {
  const base =
    scope === "class"
      ? `/workspaces/${workspaceId}/classes/${classId}/connections`
      : `/workspaces/${workspaceId}/classes/${classId}/groups/${groupId}/connections`;

  const [shared, setShared] = useState<SharedConnection[]>([]);
  const [available, setAvailable] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resourceForm, setResourceForm] = useState<Record<string, { key: string; label: string }>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, conns] = await Promise.all([
        api.get<SharedConnection[]>(base),
        api.get<Connection[]>("/connections", { workspaceId }),
      ]);
      setShared(s);
      setAvailable(conns);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [base, workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const assignedIds = new Set(shared.map((s) => s.connection_id));
  const assignable = available.filter((c) => !assignedIds.has(c.id));

  return (
    <Modal title={`Shared connections · ${label}`} onClose={onClose}>
      <p className="mb-4 text-caption leading-relaxed text-ink-faint">
        Connections shared here become context for every channel in this {scope}. Drive connections grant no file until
        you allow-list one.
      </p>

      {loading ? (
        <LoadingBlock />
      ) : (
        <div className="flex max-h-[55vh] flex-col gap-3 overflow-y-auto">
          {shared.length === 0 && <p className="text-caption text-ink-faint">Nothing shared here yet.</p>}

          {shared.map((s) => (
            <div key={s.id} className="rounded-md border border-border p-3">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="min-w-0 truncate text-small font-semibold text-ink">
                  {PROVIDER_LABEL[s.provider] ?? s.provider} · {s.label}
                </span>
                <button
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await api.delete(`${base}/${s.id}`);
                      await load();
                    } finally {
                      setBusy(false);
                    }
                  }}
                  disabled={busy}
                  className="flex-none text-caption text-ink-faint underline hover:text-crit"
                >
                  Remove
                </button>
              </div>
              {s.resources.length > 0 ? (
                <div className="mb-1.5 flex flex-col gap-1">
                  {s.resources.map((r) => (
                    <div key={r.id} className="flex items-center justify-between text-caption text-ink-dim">
                      <span className="truncate">{r.resource_label}</span>
                      <button
                        onClick={async () => {
                          await api.delete(`${base}/${s.id}/resources/${r.id}`);
                          await load();
                        }}
                        className="text-micro text-ink-faint underline hover:text-crit"
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mb-1.5 text-micro text-ink-faint">No resources allow-listed — nothing usable yet.</p>
              )}
              <div className="flex gap-1.5">
                <input
                  value={resourceForm[s.id]?.key ?? ""}
                  onChange={(e) => setResourceForm((f) => ({ ...f, [s.id]: { key: e.target.value, label: f[s.id]?.label ?? "" } }))}
                  placeholder="resource id/key"
                  className="w-1/2 rounded-md border border-border bg-transparent px-2 py-1 text-caption outline-none focus:border-border-strong"
                />
                <input
                  value={resourceForm[s.id]?.label ?? ""}
                  onChange={(e) => setResourceForm((f) => ({ ...f, [s.id]: { key: f[s.id]?.key ?? "", label: e.target.value } }))}
                  placeholder="display name"
                  className="w-1/2 rounded-md border border-border bg-transparent px-2 py-1 text-caption outline-none focus:border-border-strong"
                />
                <Button
                  size="sm"
                  onClick={async () => {
                    const form = resourceForm[s.id];
                    if (!form?.key.trim() || !form?.label.trim()) return;
                    await api.post(`${base}/${s.id}/resources`, { resource_key: form.key.trim(), resource_label: form.label.trim() });
                    setResourceForm((f) => ({ ...f, [s.id]: { key: "", label: "" } }));
                    await load();
                  }}
                >
                  Add
                </Button>
              </div>
            </div>
          ))}

          <div className="border-t border-border pt-3">
            <div className="label-sub mb-2">Share a connection</div>
            {assignable.length === 0 ? (
              <p className="text-caption text-ink-faint">Everything in this workspace is already shared here.</p>
            ) : (
              <div className="flex flex-col gap-1">
                {assignable.map((c) => (
                  <button
                    key={c.id}
                    onClick={async () => {
                      setBusy(true);
                      setError(null);
                      try {
                        await api.post(base, { connection_id: c.id });
                        await load();
                      } catch (e) {
                        setError(e instanceof ApiError ? e.message : "Failed to share");
                      } finally {
                        setBusy(false);
                      }
                    }}
                    disabled={busy}
                    className="rounded-md px-2 py-1.5 text-left text-caption text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-50"
                  >
                    {c.provider} · {c.org}
                    {c.repo && c.provider === "github" ? `/${c.repo}` : ""}
                  </button>
                ))}
              </div>
            )}
          </div>

          {error && <p className="text-caption text-crit">{error}</p>}
        </div>
      )}
    </Modal>
  );
}
