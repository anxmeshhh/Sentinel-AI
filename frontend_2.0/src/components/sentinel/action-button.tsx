import { useState } from "react";
import { ButtonGhost, ButtonSecondary } from "./primitives";

type Result = "succeeded" | "unknown" | "failed";

export interface ActionSpec {
  label: string;
  preview: string;
  detail: string;
  highRisk?: boolean;
  recipients?: { label: string; value: string }[];
  verification?: string;
  undoable?: boolean;
  result?: Result;
}

export function ActionButton({ spec }: { spec: ActionSpec }) {
  const [stage, setStage] = useState<"idle" | "preview" | "working" | "done" | "undone">(
    "idle",
  );
  const result: Result = spec.result ?? "succeeded";

  if (stage === "idle") {
    return <ButtonSecondary onClick={() => setStage("preview")}>{spec.label}</ButtonSecondary>;
  }

  if (stage === "preview" || stage === "working") {
    const risky = spec.highRisk;
    return (
      <div
        className="anim-in rounded-[4px] border p-3"
        style={{
          borderColor: risky ? "color-mix(in oklch, var(--crit) 50%, transparent)" : "var(--border)",
          background: risky
            ? "color-mix(in oklch, var(--crit) 5%, transparent)"
            : "color-mix(in oklch, var(--surface) 60%, transparent)",
        }}
      >
        {risky && (
          <p className="t-micro mb-1.5 uppercase tracking-[0.06em]" style={{ color: "var(--crit)" }}>
            High risk · cannot be undone
          </p>
        )}
        <p className="t-small text-ink">{spec.preview}</p>
        <p className="t-caption mt-1 text-ink-faint">{spec.detail}</p>
        {spec.recipients && (
          <dl className="mt-3 divide-y divide-border rounded-[3px] border border-border">
            {spec.recipients.map((r) => (
              <div key={r.label} className="flex gap-4 px-3 py-2">
                <dt className="t-micro w-20 shrink-0 text-ink-faint">{r.label}</dt>
                <dd className="t-caption text-ink-dim">{r.value}</dd>
              </div>
            ))}
          </dl>
        )}
        <div className="mt-3 flex items-center gap-2">
          {stage === "working" ? (
            <ButtonSecondary disabled>Working…</ButtonSecondary>
          ) : risky ? (
            <button
              onClick={() => {
                setStage("working");
                setTimeout(() => setStage("done"), 700);
              }}
              className="focus-ring t-small rounded-[4px] px-3 py-1.5 font-medium"
              style={{ background: "var(--crit)", color: "var(--ground)" }}
            >
              {spec.label}
            </button>
          ) : (
            <ButtonSecondary
              onClick={() => {
                setStage("working");
                setTimeout(() => setStage("done"), 700);
              }}
            >
              {spec.label}
            </ButtonSecondary>
          )}
          <ButtonGhost onClick={() => setStage("idle")}>Cancel</ButtonGhost>
        </div>
      </div>
    );
  }

  if (stage === "undone") {
    return (
      <p className="t-caption text-ink-dim">
        The change was reverted. Sentinel confirmed the previous state at the provider.
      </p>
    );
  }

  const color =
    result === "succeeded"
      ? "var(--good)"
      : result === "unknown"
        ? "var(--warn)"
        : "var(--crit)";
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
      {spec.verification && (
        <p className="t-caption mt-1 text-ink-faint">{spec.verification}</p>
      )}
      {spec.undoable && result !== "failed" && (
        <ButtonGhost className="mt-1 px-0" onClick={() => setStage("undone")}>
          Undo
        </ButtonGhost>
      )}
    </div>
  );
}
