import { useEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "./cn";

/**
 * The "more" menu.
 *
 * Exists because rows were carrying seven inline actions - Mark done, Snooze,
 * Dismiss, Prepare Me, Investigate, Ask Sentinel, Open - which is a menu
 * printed flat. A row should show the one or two things people actually do and
 * keep the rest one click away; the alternative is that every row reads as a
 * paragraph of links and nothing looks primary.
 *
 * The default trigger is a fixed 30x30 square - the same box height as an
 * `Action` button at size="sm" - so a row's "⋯" lines up with its "Done" and
 * "Open" rather than sitting a few pixels shorter, which is what made rows
 * read as slightly misaligned everywhere this was used. `trigger` lets a
 * caller replace the glyph with a labelled button (Snooze's duration menu
 * uses this) while keeping the same open/close/outside-click machinery.
 */
export function Overflow({
  children,
  label = "More actions",
  align = "right",
  className,
  trigger,
  triggerClassName,
}: {
  children: ReactNode | ((close: () => void) => ReactNode);
  label?: string;
  align?: "left" | "right";
  className?: string;
  /** Replaces the default "⋯" glyph inside the trigger button. */
  trigger?: ReactNode;
  /** Replaces the trigger button's classes entirely, for a labelled trigger
   *  that needs to look like an `Action` button rather than an icon well. */
  triggerClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  // Close on an outside click or Escape. A menu that can only be dismissed by
  // choosing something from it is a trap.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <span ref={ref} className={cn("relative inline-flex", className)}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={
          triggerClassName ??
          "flex h-[30px] w-[30px] flex-none items-center justify-center rounded-md border border-border text-ink-faint transition-colors hover:border-border-strong hover:text-ink"
        }
      >
        {trigger ?? <span aria-hidden="true">&#8943;</span>}
      </button>
      {open && (
        <span
          className={cn(
            "absolute top-8 z-20 flex min-w-[9rem] flex-col rounded-md border border-border bg-surface-2 p-1 shadow-overlay",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {typeof children === "function" ? children(() => setOpen(false)) : children}
        </span>
      )}
    </span>
  );
}

/** One row inside an Overflow. Kept here so every menu item is the same shape. */
export function OverflowItem({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="rounded-sm px-3 py-1.5 text-left text-caption text-ink-dim transition-colors hover:bg-surface-3 hover:text-ink disabled:pointer-events-none disabled:opacity-45"
    >
      {children}
    </button>
  );
}
