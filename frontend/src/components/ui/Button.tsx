import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";

import { cn } from "./cn";
import { Spinner } from "./Spinner";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

/** The audit found 22 ad-hoc button treatments alongside the system ones.
 *  These four variants cover every one of them; anything needing a fifth is
 *  a design decision, not a one-off className.
 *
 *  Only `primary` is filled, and it is filled with Sentinel purple - one per
 *  screen, marking the action the product is recommending. Two competing
 *  primaries is always a mistake, and a purple that is not a recommendation
 *  drains the colour of its meaning. */
const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-ink border border-transparent hover:bg-accent-hover",
  secondary: "bg-transparent text-ink-dim border border-border hover:border-border-strong hover:text-ink",
  ghost: "bg-transparent text-ink-faint border border-transparent hover:text-ink hover:bg-surface/70",
  danger: "bg-transparent text-crit border border-crit/30 hover:border-crit/60 hover:bg-crit/10",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "gap-1.5 px-3 py-1.5 text-caption",
  md: "gap-2 px-4 py-2.5 text-small",
};

const BASE =
  "inline-flex items-center justify-center rounded-md font-medium " +
  "transition-colors duration-200 ease-out " +
  "disabled:pointer-events-none disabled:opacity-45";

interface CommonProps {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children?: ReactNode;
}

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: CommonProps & { loading?: boolean } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button {...rest} disabled={disabled || loading} className={cn(BASE, VARIANTS[variant], SIZES[size], className)}>
      {loading && <Spinner size="sm" />}
      {children}
    </button>
  );
}

/** Same visual language for navigation, so a link that acts like a button
 *  never re-implements the styling. */
export function ButtonLink({ to, variant = "secondary", size = "md", className, children }: CommonProps & { to: string }) {
  return (
    <Link to={to} className={cn(BASE, VARIANTS[variant], SIZES[size], className)}>
      {children}
    </Link>
  );
}
