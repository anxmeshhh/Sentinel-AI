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
 */
export function Overflow({
  children,
  label = "More actions",
  align = "right",
  className,
}: {
  children: ReactNode | ((close: () => void) => ReactNode);
  label?: string;
  align?: "left" | "right";
  className?: string;
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
        className="rounded-sm px-1.5 py-0.5 text-caption leading-none text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink"
      >
        &#8943;
      </button>
      {open && (
        <span
          className={cn(
            "absolute top-6 z-20 flex min-w-[9rem] flex-col rounded-md border border-border bg-surface-2 p-1 shadow-overlay",
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
