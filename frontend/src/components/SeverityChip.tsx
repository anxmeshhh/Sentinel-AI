import type { Severity } from "../api/types";

const LABEL: Record<Severity, string> = {
  crit: "Critical",
  warn: "Warning",
  watch: "Watch",
};

const CLASSES: Record<Severity, string> = {
  crit: "bg-crit/15 text-crit",
  warn: "bg-warn/15 text-warn",
  watch: "bg-watch/15 text-watch",
};

export function SeverityChip({ severity }: { severity: Severity }) {
  return (
    <span
      className={`rounded-full px-2 py-[3px] font-mono text-[10.5px] font-bold uppercase tracking-wide ${CLASSES[severity]}`}
    >
      {LABEL[severity]}
    </span>
  );
}

export function severityStripeClass(severity: Severity): string {
  return { crit: "bg-crit", warn: "bg-warn", watch: "bg-watch" }[severity];
}
