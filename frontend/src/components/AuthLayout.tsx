import type { ReactNode } from "react";

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
    <div className="flex min-h-screen items-center justify-center bg-ground px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-10 flex flex-col items-center text-center">
          <div className="relative mb-5 h-9 w-9 rounded-full border border-ink">
            <div className="absolute inset-[8px] rounded-full bg-ink" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-balance">{title}</h1>
          <p className="mt-2 max-w-xs text-[13.5px] leading-relaxed text-ink-dim">{subtitle}</p>
        </div>

        <div className="border border-border bg-surface p-7">{children}</div>

        {footer && <div className="mt-6 text-center text-[13px] text-ink-dim">{footer}</div>}
      </div>
    </div>
  );
}

export function FieldLabel({ children }: { children: ReactNode }) {
  return <label className="mb-1.5 block text-[12.5px] font-medium text-ink-dim">{children}</label>;
}

export const inputClass =
  "w-full border border-border bg-ground px-3.5 py-2.5 text-[13.5px] text-ink outline-none transition-colors focus:border-ink placeholder:text-ink-faint";

export const primaryButtonClass =
  "w-full bg-ink py-2.5 text-[13.5px] font-semibold text-ground transition-opacity hover:opacity-90 disabled:opacity-40";

export function ErrorText({ children }: { children: ReactNode }) {
  if (!children) return null;
  return <p className="mb-4 border border-crit/30 bg-crit/10 px-3 py-2 text-[12.5px] text-crit">{children}</p>;
}
