import type { ReactNode } from "react";

import { cn } from "./cn";

/** The status vocabulary, one tone per meaning. `high` is orange and `warn`
 *  amber because the spec separates High from Medium - collapsing them was
 *  losing a whole priority step. */
export type Tone =
  | "neutral"
  | "good"
  | "warn"
  | "crit"
  | "high"
  | "watch"
  | "info"
  | "accent"
  | "outline";

/** The audit found 10 distinct badge treatments for 12 badges.
 *
 *  Colour here carries meaning (status), so the shape is constant and only
 *  the tone varies - which is what makes "ready" and "expired" comparable
 *  at a glance instead of two unrelated pills. */
const TONES: Record<Tone, string> = {
  neutral: "border-border bg-surface-2 text-ink-dim",
  good: "border-good/30 bg-good/10 text-good",
  warn: "border-warn/30 bg-warn/10 text-warn",
  crit: "border-crit/30 bg-crit/10 text-crit",
  high: "border-high/30 bg-high/10 text-high",
  watch: "border-watch/30 bg-watch/10 text-watch",
  info: "border-info/30 bg-info/10 text-info",
  accent: "border-accent/30 bg-accent/10 text-accent-text",
  outline: "border-border text-ink-faint",
};

const DOT: Record<Tone, string> = {
  neutral: "bg-ink-faint",
  good: "bg-good",
  warn: "bg-warn",
  crit: "bg-crit",
  high: "bg-high",
  watch: "bg-watch",
  info: "bg-info",
  accent: "bg-accent",
  outline: "bg-ink-faint",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex flex-none items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-micro font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** A bare state dot for dense rows, where a full badge is too heavy. */
export function StatusDot({ tone = "neutral", label }: { tone?: Tone; label?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 text-caption text-ink-dim">
      <span className={cn("h-1.5 w-1.5 flex-none rounded-full", DOT[tone])} aria-hidden="true" />
      {label}
    </span>
  );
}
