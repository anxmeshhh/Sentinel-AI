import { useState } from "react";

import { api } from "@/lib/api";
import { ButtonGhost, ButtonSecondary } from "./primitives";

/**
 * The ONLY way anything in Sentinel changes the outside world.
 *
 * Propose → preview → confirm → execute → verify → audit → (undo). Every step
 * is the server's: the preview text, the risk classification, the verification
 * line and whether an undo exists all come from the Action Registry. Nothing
 * here composes its own copy, because a client-side promise about what an
 * action will do is a promise nothing enforces.
 *
 * Three honesty rules this component exists to keep:
 *   - success is never claimed before the server verified it against the provider
 *   - `unknown` is reported as unconfirmed, never as failure - the change may
 *     well exist, and calling it a failure invites a duplicate
 *   - Undo appears only where a real inverse exists. No disabled button, no
 *     tooltip promising something that cannot happen.
 */

type Stage = "idle" | "preview" | "working" | "done" | "undoing" | "undone";
type Result = "succeeded" | "unknown" | "failed";

interface ActionResponse {
  id: string;
  status: string;
  risk: string;
  preview: Record<string, unknown>;
  verification?: string | null;
  error?: string | null;
}

export interface ActionButtonProps {
  actionType: string;
  params: Record<string, unknown>;
  label: string;
  confirmLabel?: string;
  /** Whether this action's ActionSpec declares a compensation. Passed
   *  explicitly rather than guessed, so Undo never appears when it cannot
   *  work - the same rule the backend registry follows. */
  undoable?: boolean;
  variant?: "primary" | "ghost";
  disabled?: boolean;
  onDone?: () => void;
}

export function ActionButton({
  actionType,
  params,
  label,
  confirmLabel = "Confirm",
  undoable = false,
  variant = "ghost",
  disabled,
  onDone,
}: ActionButtonProps) {
  const [stage, setStage] = useState<Stage>("idle");
  const [action, setAction] = useState<ActionResponse | null>(null);
  const [result, setResult] = useState<Result>("succeeded");
  const [verification, setVerification] = useState<string | null>(null);
  const [undoNote, setUndoNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const preview = (action?.preview ?? {}) as Record<string, unknown>;
  const irreversible = Boolean(preview["irreversible"]);

  async function propose() {
    setError(null);
    setStage("working");
    try {
      const proposed = await api.post<ActionResponse>("/actions", {
        action_type: actionType,
        params,
        source_kind: "workspace",
      });
      setAction(proposed);
      // The registry decides whether a confirmation is required. Anything
      // external comes back awaiting_approval - so this branch is the norm,
      // not the exception.
      if (proposed.status === "approved") {
        await run(proposed.id, false);
      } else {
        setStage("preview");
      }
    } catch (e) {
      setError(message(e, "Couldn't start that"));
      setStage("idle");
    }
  }

  async function run(id: string, needsApproval: boolean) {
    setError(null);
    setStage("working");
    try {
      if (needsApproval) await api.post(`/actions/${id}/approve`);
      const done = await api.post<ActionResponse>(`/actions/${id}/execute`);
      setVerification(done.verification ?? null);
      setResult(
        done.status === "succeeded" ? "succeeded" : done.status === "unknown" ? "unknown" : "failed",
      );
      if (done.status === "failed") setError(done.error ?? "The provider refused that");
      setStage("done");
      onDone?.();
    } catch (e) {
      setError(message(e, "That didn't go through"));
      setResult("failed");
      setStage("done");
    }
  }

  async function undo() {
    if (!action) return;
    setStage("undoing");
    try {
      const undone = await api.post<{ undo_result?: string | null }>(`/actions/${action.id}/undo`);
      setUndoNote(undone.undo_result ?? "The change was reverted.");
      setStage("undone");
      onDone?.();
    } catch (e) {
      setError(message(e, "Couldn't undo that"));
      setStage("done");
    }
  }

  /* ------------------------------------------------------------- rendering */

  if (stage === "undone") {
    return <p className="t-caption text-ink-dim">{undoNote}</p>;
  }

  if (stage === "done") {
    const color =
      result === "succeeded" ? "var(--good)" : result === "unknown" ? "var(--warn)" : "var(--crit)";
    const headline =
      result === "succeeded"
        ? "Done"
        : result === "unknown"
          ? "Applied, but Sentinel couldn't confirm it."
          : "Didn't run";
    return (
      <div className="anim-in">
        <p className="t-small flex items-center gap-2" style={{ color }}>
          {result === "succeeded" ? "✓" : "•"} {headline}
        </p>
        {verification && <p className="t-caption mt-1 text-ink-faint">{verification}</p>}
        {error && <p className="t-caption mt-1" style={{ color: "var(--crit)" }}>{error}</p>}
        {undoable && result !== "failed" && (
          <ButtonGhost className="mt-1 px-0" onClick={() => void undo()}>
            Undo
          </ButtonGhost>
        )}
      </div>
    );
  }

  if (stage === "preview" || (stage === "working" && action)) {
    const busy = stage === "working";
    return (
      <div
        className="anim-in rounded-[4px] border p-3"
        style={{
          borderColor: irreversible
            ? "color-mix(in oklch, var(--crit) 50%, transparent)"
            : "var(--border)",
          background: irreversible
            ? "color-mix(in oklch, var(--crit) 5%, transparent)"
            : "color-mix(in oklch, var(--surface) 60%, transparent)",
        }}
      >
        {irreversible && (
          <p
            className="t-micro mb-1.5 uppercase tracking-[0.06em]"
            style={{ color: "var(--crit)" }}
          >
            High risk · cannot be undone
          </p>
        )}

        <p className="t-small text-ink">{str(preview["summary"]) ?? label}</p>
        {str(preview["effect"]) && (
          <p className="t-caption mt-1 text-ink-faint">{str(preview["effect"])}</p>
        )}
        {str(preview["warning"]) && (
          <p className="t-caption mt-1" style={{ color: irreversible ? "var(--crit)" : "var(--warn)" }}>
            {str(preview["warning"])}
          </p>
        )}

        {/* Recipients are named individually, never counted. Nobody is
            contacted by a number. */}
        <PreviewFields preview={preview} />

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {irreversible ? (
            <button
              disabled={busy}
              onClick={() => action && void run(action.id, true)}
              className="focus-ring t-small rounded-[4px] px-3 py-1.5 font-medium disabled:opacity-50"
              style={{ background: "var(--crit)", color: "var(--ground)" }}
            >
              {busy ? "Working…" : confirmLabel}
            </button>
          ) : (
            <ButtonSecondary disabled={busy} onClick={() => action && void run(action.id, true)}>
              {busy ? "Working…" : confirmLabel}
            </ButtonSecondary>
          )}
          <ButtonGhost disabled={busy} onClick={() => setStage("idle")}>
            Cancel
          </ButtonGhost>
          {error && <span className="t-caption" style={{ color: "var(--crit)" }}>{error}</span>}
        </div>
      </div>
    );
  }

  return (
    <span className="inline-flex items-center gap-2">
      {variant === "primary" ? (
        <button
          onClick={() => void propose()}
          disabled={disabled || stage === "working"}
          className="focus-ring t-small rounded-[4px] px-3 py-1.5 font-medium disabled:opacity-50"
          style={{ background: "var(--accent)", color: "var(--accent-ink)" }}
        >
          {stage === "working" ? "…" : label}
        </button>
      ) : (
        <ButtonSecondary onClick={() => void propose()} disabled={disabled || stage === "working"}>
          {stage === "working" ? "…" : label}
        </ButtonSecondary>
      )}
      {error && <span className="t-caption" style={{ color: "var(--crit)" }}>{error}</span>}
    </span>
  );
}

/** Renders whichever descriptive fields the server's preview supplied. Reading
 *  them generically keeps this component from needing to know what any
 *  particular action does. */
function PreviewFields({ preview }: { preview: Record<string, unknown> }) {
  const rows: { label: string; value: string }[] = [];
  const to = preview["to"];
  if (Array.isArray(to) && to.length) rows.push({ label: "To", value: to.join(", ") });
  if (str(preview["subject"])) rows.push({ label: "Subject", value: str(preview["subject"])! });
  if (str(preview["when"])) rows.push({ label: "When", value: str(preview["when"])! });
  if (str(preview["message"])) rows.push({ label: "Message", value: str(preview["message"])! });
  const changes = preview["changes"];
  if (Array.isArray(changes) && changes.length)
    rows.push({ label: "Changes", value: changes.join("; ") });

  if (!rows.length) return null;
  return (
    <dl className="mt-3 divide-y divide-border rounded-[3px] border border-border">
      {rows.map((r) => (
        <div key={r.label} className="flex gap-4 px-3 py-2">
          <dt className="t-micro w-20 shrink-0 text-ink-faint">{r.label}</dt>
          <dd className="t-caption min-w-0 flex-1 whitespace-pre-wrap break-words text-ink-dim">
            {r.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v.trim() ? v : undefined;
}

function message(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}
