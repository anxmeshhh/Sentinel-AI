import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Meta } from "./Meta";
import { type Tone } from "./Badge";
import { Icon, type IconName } from "./Icon";
import { cn } from "./cn";

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

/**
 * The canonical "one thing that might need you" row.
 *
 * Every list in Sentinel - attention items, findings, situation members,
 * provider results - is the same shape, so it should be the same component.
 * Before this, each page laid its own out and they drifted: different title
 * weights, the provider name sometimes right-aligned and sometimes inline,
 * actions as links here and buttons there.
 *
 * The information hierarchy is enforced by the props, not by convention:
 *
 *   tone + title   LEVEL 1  what matters        (always visible, one line)
 *   source + meta  LEVEL 2  key context         (chips, scannable)
 *   actions        LEVEL 3  what to do          (uniform, right-aligned)
 *   details        LEVEL 4  the long explanation (behind a disclosure)
 *
 * There is no prop for a paragraph. That is the point - explanatory prose goes
 * in `details` and stays closed until someone asks for it.
 */
export function ItemRow({
  tone = "neutral",
  icon,
  title,
  source,
  meta,
  badge,
  actions,
  to,
  details,
  children,
  muted = false,
  className,
}: {
  tone?: Tone;
  /** What kind of thing this is, as a glyph. The severity dot says how urgent;
   *  this says what it is, so the two are never conflated into one signal. */
  icon?: IconName;
  title: ReactNode;
  source?: string | null;
  meta?: (string | null | undefined | false)[];
  /** A priority/status pill sitting with the metadata. */
  badge?: ReactNode;
  actions?: ReactNode;
  /** Renders the title as a link into the detail surface. */
  to?: string;
  /** The long explanation. Collapsed by default; the row grows a "Why"
   *  toggle only when there is something to show. */
  details?: ReactNode;
  /** Surfaces that belong to this row and open beneath it - a meeting brief,
   *  an investigation result. Kept inside the row so they stay visually
   *  attached to the thing they are about. */
  children?: ReactNode;
  /** Done/dismissed items stay legible but stop competing. */
  muted?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className={cn("group px-4 py-3 transition-colors hover:bg-surface/50", className)}>
      <div className="flex items-start gap-3">
        <span
          className={cn("mt-[11px] h-1.5 w-1.5 flex-none rounded-full", DOT[tone])}
          aria-hidden="true"
        />

        {icon && (
          <span
            className="mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-md border border-border bg-surface-2 text-ink-faint"
            aria-hidden="true"
          >
            <Icon name={icon} size={15} />
          </span>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <p
              className={cn(
                "min-w-0 text-small font-medium leading-snug",
                muted ? "text-ink-faint line-through" : "text-ink",
              )}
            >
              {to ? (
                <Link to={to} className="transition-colors hover:text-white">
                  {title}
                </Link>
              ) : (
                title
              )}
            </p>
            <div className="flex-none">{actions}</div>
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Meta source={source} items={meta} />
            {badge}
            {details && (
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="text-micro text-ink-faint underline-offset-2 transition-colors hover:text-ink-dim hover:underline"
                aria-expanded={open}
              >
                {open ? "Less" : "Why"}
              </button>
            )}
          </div>

          {open && details && (
            <div className="mt-2 border-l border-rule pl-3 text-caption leading-relaxed text-ink-dim">
              {details}
            </div>
          )}

          {children && <div className="mt-3">{children}</div>}
        </div>
      </div>
    </div>
  );
}

/** A bordered list of ItemRows with hairlines between them. Keeps every list
 *  in the product the same object instead of six variations on a card. */
export function ItemList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("divide-y divide-rule overflow-hidden rounded-lg border border-border", className)}>
      {children}
    </div>
  );
}
