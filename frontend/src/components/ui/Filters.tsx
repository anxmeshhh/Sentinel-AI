import { cn } from "./cn";

/**
 * The one filter control.
 *
 * Situations, Attention and the action audit each grew their own row of
 * pill buttons - same job, three different radii, paddings and selected
 * treatments. Selection is shown with a fill because the design system
 * reserves fill for exactly that: hover and selection.
 */
export function FilterChips<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: readonly { key: T; label: string; count?: number }[];
  value: T;
  onChange: (key: T) => void;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap gap-1", className)} role="tablist">
      {options.map((o) => {
        const selected = o.key === value;
        return (
          <button
            key={o.key}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(o.key)}
            className={cn(
              "rounded-md px-2.5 py-1 text-caption transition-colors duration-200",
              selected ? "bg-surface-2 text-ink" : "text-ink-faint hover:text-ink-dim",
            )}
          >
            {o.label}
            {o.count !== undefined && <span className="ml-1.5 text-ink-faint">{o.count}</span>}
          </button>
        );
      })}
    </div>
  );
}
