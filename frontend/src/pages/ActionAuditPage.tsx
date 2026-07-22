import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api/client";
import type { SentinelAction } from "../api/types";
import { EmptyState, LoadingBlock } from "../components/ui";

const STATUS_COPY: Record<string, { label: string; tone: string }> = {
  succeeded: { label: "Succeeded", tone: "text-good" },
  failed: { label: "Failed", tone: "text-crit" },
  unknown: { label: "Unconfirmed", tone: "text-watch" },
  rejected: { label: "Declined", tone: "text-ink-faint" },
  cancelled: { label: "Cancelled", tone: "text-ink-faint" },
};

/**
 * What Sentinel actually changed in this workspace.
 *
 * Admin-only, because it spans everyone's actions - it answers "what did this
 * system do here", which belongs to whoever is responsible for the workspace
 * rather than to every member.
 *
 * Deliberately plain. An audit surface earns trust by being boring and
 * complete: who asked, who approved, what ran, where, when, what came back,
 * and how the outcome was confirmed. Nothing here renders a token or a
 * message body, because the server never put one in the record.
 */
export function ActionAuditPage() {
  const [actions, setActions] = useState<SentinelAction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setActions(await api.get<SentinelAction[]>("/workspaces/audit/actions"));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't load the audit trail");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingBlock />;
  if (error) {
    return <EmptyState title="Audit trail unavailable" description={error} />;
  }
  if (actions.length === 0) {
    return (
      <EmptyState
        title="Sentinel hasn't changed anything yet"
        description="Every action Sentinel executes in this workspace will be recorded here — what ran, who approved it, and whether the outcome was confirmed."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-h2 font-semibold text-ink">Action history</h1>
        <p className="mt-1 text-small leading-relaxed text-ink-dim">
          Everything Sentinel has executed in this workspace. Credentials and message contents are never recorded.
        </p>
      </div>

      <div className="card divide-y divide-border">
        {actions.map((a) => {
          const status = STATUS_COPY[a.status] ?? STATUS_COPY.unknown;
          const open = expanded === a.id;
          return (
            <div key={a.id} className="p-3.5">
              <button
                onClick={() => setExpanded(open ? null : a.id)}
                className="flex w-full items-start justify-between gap-3 text-left"
              >
                <div className="min-w-0">
                  <div className="text-small font-semibold text-ink">
                    {a.preview.title ?? a.action_type}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-2 text-micro text-ink-faint">
                    <span className="font-mono">{a.action_type}</span>
                    <span>· {a.executed_at ? new Date(a.executed_at).toLocaleString() : "not run"}</span>
                    <span>· {a.risk} risk</span>
                    {a.undone_at && <span className="text-watch">· undone</span>}
                  </div>
                </div>
                <span className={`flex-none font-mono text-micro uppercase tracking-wide ${status.tone}`}>
                  {status.label}
                </span>
              </button>

              {open && (
                <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3 text-caption">
                  <Row label="Requested by" value={a.requested_by_user_id} mono />
                  <Row label="Approved by" value={a.approved_by_user_id ?? "—"} mono />
                  <Row
                    label="Approved at"
                    value={a.approved_at ? new Date(a.approved_at).toLocaleString() : "—"}
                  />
                  <Row label="Scope" value={a.source_kind ? `via ${a.source_kind}` : "direct request"} />

                  {a.reason && <Row label="Why" value={a.reason} />}

                  {/* What the user was shown before approving. */}
                  {Object.entries(a.preview.fields ?? {}).map(([k, v]) => (
                    <Row key={k} label={k} value={String(v)} />
                  ))}

                  {/* How the outcome was confirmed - the difference between
                      "we called the API" and "we checked". */}
                  {a.verification && <Row label="Verified" value={a.verification} />}
                  {a.error && <Row label="Error" value={a.error} tone="text-crit" />}
                  {a.undo_result && <Row label="Undone" value={a.undo_result} tone="text-watch" />}

                  {Boolean(a.result?.url) && (
                    <Row
                      label="Link"
                      value={
                        <a
                          href={String(a.result.url)}
                          target="_blank"
                          rel="noreferrer"
                          className="text-accent-text hover:underline"
                        >
                          open in provider
                        </a>
                      }
                    />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  mono = false,
  tone = "text-ink-dim",
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  tone?: string;
}) {
  return (
    <div className="flex gap-3">
      <span className="w-28 flex-none text-ink-faint">{label}</span>
      <span className={`min-w-0 flex-1 ${mono ? "font-mono text-micro" : ""} ${tone}`}>{value}</span>
    </div>
  );
}
