import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

import { cn } from "./cn";

/** The audit found 13 distinct input signatures across 26 inputs - different
 *  padding, radius and text size on controls doing the same job. This is the
 *  one treatment. */
const CONTROL =
  "w-full rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink " +
  "transition-colors duration-200 placeholder:text-ink-faint " +
  "focus:border-border-strong focus:outline-none focus:ring-2 focus:ring-ink/10 " +
  "disabled:cursor-not-allowed disabled:opacity-50";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={cn(CONTROL, className)} />;
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...rest} className={cn(CONTROL, "resize-y", className)} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={cn(CONTROL, "cursor-pointer", className)}>
      {children}
    </select>
  );
}

/** Label + control + hint/error, so the vertical rhythm around a form field
 *  is decided once. */
export function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
  className,
}: {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {label && (
        <label htmlFor={htmlFor} className="text-caption font-medium text-ink-dim">
          {label}
        </label>
      )}
      {children}
      {error ? (
        <p className="text-caption text-crit">{error}</p>
      ) : (
        hint && <p className="text-caption text-ink-faint">{hint}</p>
      )}
    </div>
  );
}
