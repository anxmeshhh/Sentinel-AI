import type { ReactNode } from "react";

import { cn } from "./cn";

/** Wide tables must scroll inside their own container - the page body never
 *  scrolls horizontally. */
export function TableWrap({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-x-auto rounded-md border border-border", className)}>
      <table className="w-full border-collapse text-small">{children}</table>
    </div>
  );
}

export function Th({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <th
      className={cn(
        "border-b border-rule-strong px-4 py-3 text-left text-caption font-medium text-ink-faint",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function Td({ children, className }: { children: ReactNode; className?: string }) {
  return <td className={cn("border-b border-rule px-4 py-3 align-top text-ink-dim", className)}>{children}</td>;
}

export function Tr({ children, className }: { children: ReactNode; className?: string }) {
  return <tr className={cn("transition-colors duration-150 hover:bg-surface/60", className)}>{children}</tr>;
}

/** Dense list rows sharing one hairline rule - the alternative to a table
 *  when there are no columns to align. */
export function Rows({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("rule-rows", className)}>{children}</div>;
}
