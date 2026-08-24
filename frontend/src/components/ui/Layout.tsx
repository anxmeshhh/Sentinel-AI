import type { ReactNode } from "react";

import { cn } from "./cn";

/**
 * The page header. One of them, for every page.
 *
 * There were three: a `.section-head` grid (Mail, Drive, Meet, History,
 * Settings), a `text-h2 font-medium text-balance` variant with an eyebrow
 * (Calendar, Admin, the detail pages), and the hand-rolled `<header
 * className="mb-5">` the redesigned pages converged on. A `PageHeader`
 * component also existed and was imported by nothing - a fourth design,
 * dead in the file.
 *
 * This is the third one, because that is what Attention, Findings,
 * Situations, Goals, Memory and the Assistant already use and what the
 * product now reads as. Consolidating here means the spacing above a page's
 * content is decided once: the drift between `mb-4` and `mb-5` and `mb-7`
 * was invisible on any single page and obvious when moving between them.
 */
export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  /** Right-aligned controls - a Sync Now, a "+ New Goal". Wraps below the
   *  title on narrow screens rather than crushing it. */
  actions?: ReactNode;
  /** Which context this page belongs to ("Personal", "Operator"). Only worth
   *  showing where a page could otherwise be mistaken for another scope. */
  eyebrow?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-5 flex flex-wrap items-start justify-between gap-3", className)}>
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
        <h1 className="text-h2 font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-[68ch] text-small text-ink-dim">{description}</p>}
      </div>
      {actions && <div className="flex flex-none items-center gap-2">{actions}</div>}
    </header>
  );
}

/** A titled block within a page. One interval between sections, everywhere. */
export function Section({
  title,
  description,
  action,
  children,
  className,
}: {
  title?: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("mb-10 last:mb-0 sm:mb-14", className)}>
      {(title || action) && (
        <div className="mb-5 flex items-end justify-between gap-4">
          <div className="min-w-0">
            {title && <h2 className="text-title font-semibold text-ink">{title}</h2>}
            {description && <p className="mt-1.5 max-w-[58ch] text-caption text-ink-dim">{description}</p>}
          </div>
          {action && <div className="flex-none">{action}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

/** A horizontal rule used as a section divider. Dimmer than a card border:
 *  this is structure, not an edge. */
export function Divider({ className }: { className?: string }) {
  return <hr className={cn("border-0 border-t border-rule", className)} />;
}
