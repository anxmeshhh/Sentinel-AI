import { cn } from "./cn";

const SIZES = { sm: "h-3.5 w-3.5 border", md: "h-5 w-5 border-2" } as const;

/** Replaces 17 hand-written "Loading…" literals. A spinner rather than text
 *  because the word was appearing at seven different sizes and colours. */
export function Spinner({ size = "md", className }: { size?: keyof typeof SIZES; className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn(
        "inline-block flex-none animate-spin rounded-full border-ink-faint border-t-transparent",
        SIZES[size],
        className,
      )}
    />
  );
}

/** Centred block loader for a whole pane. */
export function LoadingBlock({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-16 text-caption text-ink-faint">
      <Spinner size="sm" />
      {label}
    </div>
  );
}
