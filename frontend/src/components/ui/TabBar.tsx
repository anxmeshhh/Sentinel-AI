import type { ReactNode } from "react";

import { cn } from "./cn";

export interface TabBarItem<K extends string> {
  key: K;
  label: string;
  /** A small count pill - omitted when undefined, never rendered as 0. */
  count?: number;
}

/**
 * The one local-state underline tab bar, extracted from Situations and
 * Findings so a third page (any provider page) reaches for this instead of
 * hand-rolling the same `border-b-2 border-accent` treatment a third time.
 * Route-driven navigation still uses `Tabs` (ui/Tabs.tsx) - this is for
 * switching content within one page.
 */
export function TabBar<K extends string>({
  items,
  value,
  onChange,
  trailing,
}: {
  items: TabBarItem<K>[];
  value: K;
  onChange: (key: K) => void;
  /** e.g. a Filter dropdown, right-aligned on the same row. */
  trailing?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-2 border-b border-border">
      <div role="tablist" className="flex gap-1">
        {items.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={value === item.key}
            onClick={() => onChange(item.key)}
            className={cn(
              "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-small transition-colors",
              value === item.key
                ? "border-accent font-semibold text-ink"
                : "border-transparent text-ink-faint hover:text-ink-dim",
            )}
          >
            {item.label}
            {item.count !== undefined && item.count > 0 && (
              <span className="rounded-full bg-surface-2 px-1.5 py-px font-mono text-micro text-ink-dim">
                {item.count}
              </span>
            )}
          </button>
        ))}
      </div>
      {trailing && <div className="pb-1.5">{trailing}</div>}
    </div>
  );
}
