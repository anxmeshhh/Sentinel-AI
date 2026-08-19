import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { cn } from "./cn";

/** The single card treatment.
 *
 *  The interior is the page's own black - the border defines the card, not
 *  a fill. That is what keeps a grid of them reading as a calm structure
 *  rather than a stack of trays. Fill is reserved for hover and selection,
 *  where it means something. */
export function Card({
  children,
  className,
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return <div className={cn("rounded-lg border border-border", padded && "p-6 sm:p-7", className)}>{children}</div>;
}

export function CardLink({
  to,
  children,
  className,
  selected = false,
}: {
  to: string;
  children: ReactNode;
  className?: string;
  selected?: boolean;
}) {
  return (
    <Link
      to={to}
      className={cn(
        "block rounded-lg border p-6 transition-colors duration-200 ease-out sm:p-7",
        selected ? "border-ink-faint bg-surface/60" : "border-border hover:border-border-strong hover:bg-surface/60",
        className,
      )}
    >
      {children}
    </Link>
  );
}

export function CardButton({
  onClick,
  children,
  className,
  selected = false,
}: {
  onClick: () => void;
  children: ReactNode;
  className?: string;
  selected?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "block w-full rounded-md border p-6 text-left transition-colors duration-200 ease-out sm:p-7",
        selected ? "border-ink-faint bg-surface/60" : "border-border hover:border-border-strong hover:bg-surface/60",
        className,
      )}
    >
      {children}
    </button>
  );
}

/** Cards sit apart with real gaps, each owning its full border. */
export function CardGrid({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("grid gap-4 sm:gap-5", className)}>{children}</div>;
}

export function CardHeader({
  title,
  description,
  action,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h3 className="text-lead font-semibold text-ink">{title}</h3>
        {description && <p className="mt-1.5 text-caption text-ink-dim">{description}</p>}
      </div>
      {action && <div className="flex-none">{action}</div>}
    </div>
  );
}
