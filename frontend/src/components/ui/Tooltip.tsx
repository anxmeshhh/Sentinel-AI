import type { ReactNode } from "react";

import { cn } from "./cn";

/** CSS-only tooltip.
 *
 *  The audit found 20 native `title=` attributes and no shared tooltip.
 *  Native titles are unstyleable, take ~1s to appear, and never show on
 *  touch - fine for a hint, wrong for anything a user needs. This is
 *  hover/focus driven so keyboard users get it too.
 *
 *  Deliberately CSS-only: a positioned-portal tooltip is a real component
 *  with real edge cases, and nothing here needs one yet. */
export function Tooltip({
  label,
  children,
  side = "top",
  className,
}: {
  label: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom";
  className?: string;
}) {
  return (
    <span className={cn("group/tt relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute left-1/2 z-50 hidden -translate-x-1/2 whitespace-nowrap",
          "rounded-md border border-border bg-surface-2 px-2.5 py-1 text-micro text-ink shadow-overlay",
          "group-hover/tt:block group-focus-within/tt:block",
          side === "top" ? "bottom-full mb-2" : "top-full mt-2",
        )}
      >
        {label}
      </span>
    </span>
  );
}
