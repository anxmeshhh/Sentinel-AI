import type { ReactNode } from "react";
import { Link } from "react-router-dom";

interface ServiceCardProps {
  icon: ReactNode;
  name: string;
  status: string;
  desc: string;
  connected: boolean;
  // Explicit colour for the status line. Defaults to connected? good : muted,
  // but a failing/revoked connection needs to read red even though it is
  // "connected" in the sense that a row exists.
  statusTone?: "good" | "warn" | "crit" | "muted";
  active?: boolean;
  disabled?: boolean;
  to?: string;
  onClick?: () => void;
  onRemove?: () => void;
}

// One card visual, used everywhere a connection or service needs to be
// represented: the dashboard's top-level provider grid and each Connection
// Workspace's individual service grid underneath it. `to` navigates via
// router; `onClick` handles in-page state (used nowhere left after the
// workspace-page split, kept for flexibility).
const TONE_CLASS = {
  good: "text-good",
  warn: "text-warn",
  crit: "text-crit",
  muted: "text-ink-faint",
} as const;

export function ServiceCard({ icon, name, status, desc, connected, statusTone, active, disabled, to, onClick, onRemove }: ServiceCardProps) {
  const toneClass = TONE_CLASS[statusTone ?? (connected ? "good" : "muted")];
  const className = `relative flex h-full flex-col rounded-md border p-5 text-left transition-colors ${
    active ? "border-ink-faint bg-surface/60" : "border-border hover:border-border-strong hover:bg-surface/40"
  } ${disabled ? "opacity-70" : ""}`;

  const content = (
    <>
      {onRemove && (
        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onRemove();
          }}
          aria-label={`Disconnect ${name}`}
          className="absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full text-ink-faint hover:bg-crit/15 hover:text-crit"
        >
          ✕
        </button>
      )}
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-md bg-surface-2">{icon}</div>
      <div className="mb-1 pr-4 text-lead font-semibold leading-tight text-ink">{name}</div>
      <div className={`mb-2 text-small font-semibold ${toneClass}`}>{status}</div>
      <div className="text-caption leading-relaxed text-ink-faint">{desc}</div>
    </>
  );

  if (to) {
    // `disabled` is purely visual (dimmed) here - a "coming soon" card still
    // navigates, landing on a page that explains what's not built yet,
    // rather than being a dead button with no explanation.
    return (
      <Link to={to} className={className}>
        {content}
      </Link>
    );
  }
  return (
    <button onClick={onClick} disabled={disabled && !onRemove} className={className}>
      {content}
    </button>
  );
}
