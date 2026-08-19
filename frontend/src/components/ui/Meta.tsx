import type { ReactNode } from "react";

import { Badge } from "./Badge";
import { cn } from "./cn";

/**
 * Key context, compressed.
 *
 * This replaces the explanatory sentence under every row. "Was due 1d ago in
 * Tasks — marked high importance" is a sentence a person has to read;
 * `Tasks · 1 day overdue · High importance` is three facts they can scan. Same
 * information, a third of the reading.
 *
 * The source (which service this came from) is a badge because it is the one
 * piece of context people filter on visually; everything else is dot-separated
 * micro text, deliberately recessive.
 */
export function Meta({
  source,
  items,
  className,
}: {
  source?: string | null;
  /** Falsy entries are dropped, so callers can inline conditionals without
   *  producing stray separators. */
  items?: (string | null | undefined | false)[];
  className?: string;
}) {
  const facts = (items ?? []).filter((i): i is string => Boolean(i));
  if (!source && facts.length === 0) return null;

  return (
    <div className={cn("flex flex-wrap items-center gap-x-2 gap-y-1 text-micro text-ink-faint", className)}>
      {source && <Badge tone="outline">{source}</Badge>}
      {facts.map((f, i) => (
        <span key={i} className="inline-flex items-center gap-2">
          {i > 0 && <span aria-hidden="true">·</span>}
          {f}
        </span>
      ))}
    </div>
  );
}

/** A count paired with its noun, for rail entries and card footers where a
 *  sentence would be three words too many. */
export function MetaCount({ value, label }: { value: number; label: string }) {
  return (
    <span className="text-caption text-ink-dim">
      <span className="font-medium text-ink">{value}</span> {label}
    </span>
  );
}

export function MetaWrap({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("flex flex-wrap items-center gap-x-2 gap-y-1", className)}>{children}</div>;
}
