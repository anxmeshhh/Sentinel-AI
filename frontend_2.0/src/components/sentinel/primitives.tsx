import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { severityColor, severityLabel, type Severity } from "@/lib/sentinel-data";

export function SectionLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn("label-micro", className)}>{children}</div>;
}

export function Dot({ color, size = 6 }: { color: string; size?: number }) {
  return (
    <span
      aria-hidden
      className="inline-block shrink-0 rounded-full"
      style={{ width: size, height: size, background: color }}
    />
  );
}

export function SeverityMark({
  severity,
  withWord = true,
}: {
  severity: Severity;
  withWord?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <Dot color={severityColor[severity]} />
      {withWord && (
        <span className="t-micro" style={{ color: severityColor[severity] }}>
          {severityLabel[severity]}
        </span>
      )}
    </span>
  );
}

export function Pill({
  children,
  color = "var(--ink-faint)",
  className,
}: {
  children: ReactNode;
  color?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "t-micro inline-flex items-center gap-1.5 rounded-[2px] border px-1.5 py-0.5 uppercase tracking-[0.06em]",
        className,
      )}
      style={{ borderColor: color, color }}
    >
      {children}
    </span>
  );
}

export function Panel({
  children,
  className,
  accent,
  as = "div",
}: {
  children: ReactNode;
  className?: string;
  accent?: string;
  as?: "div" | "li";
}) {
  const Tag = as;
  return (
    <Tag
      className={cn("rounded-[4px] border border-border bg-surface-2 p-4", className)}
      style={accent ? { borderLeft: `2px solid ${accent}` } : undefined}
    >
      {children}
    </Tag>
  );
}

export function ButtonPrimary({
  children,
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className={cn(
        "focus-ring t-small inline-flex items-center justify-center rounded-[4px] bg-accent px-3 py-1.5 font-medium text-accent-ink transition-opacity duration-150 hover:opacity-90 disabled:opacity-50",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function ButtonSecondary({
  children,
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className={cn(
        "focus-ring t-small inline-flex items-center justify-center rounded-[4px] border border-border px-3 py-1.5 text-ink-dim transition-colors duration-150 hover:border-border-strong hover:text-ink disabled:opacity-50",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function ButtonGhost({
  children,
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className={cn(
        "focus-ring t-caption inline-flex items-center gap-1.5 rounded-[3px] px-2 py-1 text-ink-faint transition-colors duration-150 hover:text-ink",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-[4px] border border-dashed border-border px-6 py-10 text-center">
      <p className="t-small text-ink">{title}</p>
      {body && (
        <p className="t-caption mx-auto mt-1.5 max-w-[52ch] text-ink-faint">{body}</p>
      )}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton h-10 w-full" />
      ))}
    </div>
  );
}

export function InlineError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <p className="t-caption flex items-center gap-3" style={{ color: "var(--crit)" }}>
      {message}
      {onRetry && (
        <button onClick={onRetry} className="underline underline-offset-2">
          Retry
        </button>
      )}
    </p>
  );
}

export function PageHeader({
  title,
  caption,
  right,
}: {
  title: string;
  caption?: string;
  right?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="t-h2 font-medium text-ink">{title}</h1>
        {caption && <p className="t-caption mt-1 text-ink-dim">{caption}</p>}
      </div>
      {right}
    </header>
  );
}
