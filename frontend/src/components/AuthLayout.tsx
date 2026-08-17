import type { ReactNode } from "react";

/**
 * The signed-out shell.
 *
 * Tightened from a centred stack that ran ~250px of empty space before the
 * first word and then let the card breathe so loosely it needed scrolling on a
 * laptop. Sign-in is a task, not a landing page: the whole of it should be
 * visible at once, with the mark and heading present but small.
 *
 * Square corners and a border-defined card, matching the rest of the product -
 * this is the first screen anyone sees, so it has to look like the same app.
 */
export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-ground px-4 py-10">
      <div className="w-full max-w-[380px]">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="relative h-[18px] w-[18px] flex-none rounded-full border border-ink" aria-hidden="true">
            <span className="absolute inset-[5px] rounded-full bg-ink" />
          </span>
          <span className="text-small font-semibold tracking-tight text-ink">Sentinel</span>
        </div>

        <h1 className="text-h3 font-semibold tracking-tight text-balance text-ink">{title}</h1>
        <p className="mt-1.5 text-small leading-relaxed text-ink-dim">{subtitle}</p>

        <div className="mt-6 rounded-md border border-border bg-surface p-5">{children}</div>

        {footer && <div className="mt-5 text-small text-ink-dim">{footer}</div>}
      </div>
    </div>
  );
}

export function FieldLabel({ children }: { children: ReactNode }) {
  return <label className="mb-1 block text-caption font-medium text-ink-dim">{children}</label>;
}

export const inputClass =
  "w-full rounded-md border border-border bg-ground px-3 py-2 text-small text-ink outline-none transition-colors focus:border-border-strong placeholder:text-ink-faint";

export const primaryButtonClass =
  "w-full rounded-md bg-ink py-2 text-small font-semibold text-ground transition-opacity hover:opacity-90 disabled:opacity-40";

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <p className="mb-3 rounded-md border border-crit/30 bg-crit/10 px-3 py-2 text-caption text-crit">
      {children}
    </p>
  );
}
