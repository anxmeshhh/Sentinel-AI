import type { ReactNode } from "react";

import { cn } from "./cn";

/** Page header: heading left, supporting copy right, stacking on mobile.
 *
 *  Owns its own spacing. The audit found ten distinct `mb-*` values on
 *  section wrappers - that drift is what makes pages feel like different
 *  products, and it only stops if the spacing lives in one place. */
export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-8 sm:mb-10", className)}>
      {eyebrow && <p className="mb-2.5 text-caption font-medium text-ink-faint">{eyebrow}</p>}
      <div className="grid gap-x-10 gap-y-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-h2 font-semibold text-balance text-ink">{title}</h1>
          {actions && <div className="flex flex-none items-center gap-2 lg:hidden">{actions}</div>}
        </div>
        <div className="flex items-start justify-between gap-4">
          {description && <p className="max-w-[54ch] text-body text-ink-dim lg:pt-1">{description}</p>}
          {actions && <div className="hidden flex-none items-center gap-2 lg:flex">{actions}</div>}
        </div>
      </div>
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
