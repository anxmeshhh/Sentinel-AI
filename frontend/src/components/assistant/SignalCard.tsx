import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Icon, type IconName, cn } from "../ui";

/**
 * The three cards the Assistant opens with.
 *
 * This is the "proactive" half of the product claim: before anyone types
 * anything, Sentinel has already said what it found. Each card is one thing
 * the Core concluded - a Situation, an upcoming meeting, a Memory - with the
 * single next step attached.
 *
 * Every card is rendered from real engine output or not rendered at all.
 * There is no placeholder variant, because a card that says "no deployment
 * issues" is noise, and a card invented to fill a three-across grid would be
 * the exact fabrication the architecture exists to prevent.
 */
export type SignalTone = "critical" | "upcoming" | "insight";

const TONES: Record<
  SignalTone,
  { label: string; icon: IconName; ring: string; chip: string; text: string; orb: string }
> = {
  critical: {
    label: "Critical",
    icon: "alert",
    ring: "border-crit/30 bg-crit/[0.07] hover:border-crit/50",
    chip: "bg-crit/15 text-crit",
    text: "text-crit",
    orb: "bg-crit/15 text-crit",
  },
  upcoming: {
    label: "Upcoming",
    icon: "clock",
    ring: "border-warn/30 bg-warn/[0.07] hover:border-warn/50",
    chip: "bg-warn/15 text-warn",
    text: "text-warn",
    orb: "bg-warn/15 text-warn",
  },
  insight: {
    label: "Insight",
    icon: "brain",
    ring: "border-good/30 bg-good/[0.07] hover:border-good/50",
    chip: "bg-good/15 text-good",
    text: "text-good",
    orb: "bg-good/15 text-good",
  },
};

export function SignalCard({
  tone,
  title,
  body,
  meta,
  actionLabel,
  to,
  onAction,
  busy,
}: {
  tone: SignalTone;
  title: string;
  body: string;
  meta?: ReactNode;
  actionLabel: string;
  /** Either navigate… */
  to?: string;
  /** …or do something in place. One of the two, never both. */
  onAction?: () => void;
  busy?: boolean;
}) {
  const t = TONES[tone];

  return (
    <div
      className={cn(
        "flex min-w-0 flex-col rounded-lg border p-4 transition-colors duration-200",
        t.ring,
      )}
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <span
          className={cn(
            "inline-flex flex-none items-center rounded-full px-2 py-0.5 text-micro font-semibold uppercase tracking-wide",
            t.chip,
          )}
        >
          {t.label}
        </span>
        <span
          className={cn("flex h-8 w-8 flex-none items-center justify-center rounded-full", t.orb)}
          aria-hidden="true"
        >
          <Icon name={t.icon} size={15} />
        </span>
      </div>

      <p className="text-small font-semibold leading-snug text-ink">{title}</p>
      <p className="mt-1 line-clamp-2 text-caption leading-relaxed text-ink-dim">{body}</p>

      {meta && <div className="mt-2.5">{meta}</div>}

      <div className="mt-auto pt-3">
        {to ? (
          <Link
            to={to}
            className={cn("inline-flex items-center gap-1 text-caption font-medium", t.text)}
          >
            {actionLabel} <span aria-hidden="true">→</span>
          </Link>
        ) : (
          <button
            type="button"
            onClick={onAction}
            disabled={busy}
            className={cn(
              "inline-flex items-center gap-1 text-caption font-medium disabled:opacity-50",
              t.text,
            )}
          >
            {busy ? "Working…" : actionLabel} <span aria-hidden="true">→</span>
          </button>
        )}
      </div>
    </div>
  );
}
