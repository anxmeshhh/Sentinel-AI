import type { ReactNode } from "react";

import { cn } from "./cn";

/** The audit found 10 distinct dashed-border empty states across 23 uses.
 *
 *  An empty state has to answer two questions - what is missing, and what
 *  do I do about it - so `title` and `action` are first-class rather than
 *  something each page improvises. `description` is where the *reason*
 *  goes, which matters here: an empty channel because nothing happened and
 *  an empty channel because you haven't connected Gmail are different news. */
export function EmptyState({
  title,
  description,
  action,
  className,
  compact = false,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-md border border-dashed border-border text-center",
        compact ? "px-5 py-8" : "px-6 py-16",
        className,
      )}
    >
      <p className="text-body font-medium text-ink-dim">{title}</p>
      {description && (
        <p className="mx-auto mt-2 max-w-[46ch] text-caption leading-relaxed text-ink-faint">{description}</p>
      )}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}
