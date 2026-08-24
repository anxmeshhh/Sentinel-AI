import type { ReactNode } from "react";

import { Icon, type IconName } from "../ui";
import { cn } from "../ui/cn";
import { Reveal } from "./Reveal";

/**
 * The landing page's shared furniture.
 *
 * Deliberately thin. Everything visual here is either a design-system
 * component or a token - the landing page borrows the product's language
 * rather than inventing a second one, which is what stops it feeling like a
 * different company's website.
 *
 * The one place it departs is display type: the product's scale tops out at
 * 28px because a page heading should never shout over its content. A hero
 * has the opposite job, so the sizes below are landing-local rather than a
 * change to the shared scale.
 */

export function Section({
  id,
  children,
  className,
}: {
  id?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={cn("mx-auto w-full max-w-6xl px-5 py-20 sm:px-8 sm:py-28", className)}>
      {children}
    </section>
  );
}

/** The small monospace label above a section title. Same `eyebrow` treatment
 *  the product already uses, so section openings rhyme across both. */
export function Eyebrow({ children }: { children: ReactNode }) {
  return <p className="eyebrow mb-4">{children}</p>;
}

export function SectionHeading({
  eyebrow,
  title,
  lede,
  className,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  lede?: ReactNode;
  className?: string;
}) {
  return (
    <Reveal className={cn("mb-12 max-w-2xl sm:mb-16", className)}>
      {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
      <h2 className="text-[clamp(26px,4vw,40px)] font-semibold leading-[1.15] tracking-[-0.03em] text-ink">
        {title}
      </h2>
      {lede && (
        <p className="mt-4 max-w-[60ch] text-[clamp(15px,1.6vw,17px)] leading-relaxed text-ink-dim">{lede}</p>
      )}
    </Reveal>
  );
}

/** A hairline that reads as structure rather than an edge - the same
 *  distinction `rule` vs `border` makes in the product. */
export function Hairline({ className }: { className?: string }) {
  return <div className={cn("mx-auto w-full max-w-6xl px-5 sm:px-8", className)}>
    <div className="h-px w-full bg-rule" />
  </div>;
}

/* ------------------------------------------------------------- pipeline -- */

export interface Stage {
  key: string;
  label: string;
  plain: string;
  icon: IconName;
}

/** The Core, in the order the code actually runs it. */
export const PIPELINE: Stage[] = [
  { key: "signals", label: "Signals", plain: "Something happened.", icon: "activity" },
  { key: "findings", label: "Findings", plain: "Sentinel noticed it.", icon: "alert" },
  { key: "situations", label: "Situations", plain: "It connected it to something else.", icon: "layers" },
  { key: "reasoning", label: "Reasoning", plain: "It worked out why that matters.", icon: "sparkle" },
  { key: "memory", label: "Memory", plain: "It remembered this keeps happening.", icon: "brain" },
  { key: "decisions", label: "Decisions", plain: "It proposed what to do.", icon: "flag" },
  { key: "goals", label: "Goals", plain: "It checked what this costs you.", icon: "target" },
  { key: "actions", label: "Actions", plain: "And it can do it — once you say yes.", icon: "check" },
];

/**
 * The vertical pipeline used in the hero.
 *
 * A travelling dot rather than eight animated rows: one moving element reads
 * as flow, eight read as noise. The dot's delay is derived from its index so
 * the sequence stays in step however many stages there are.
 */
export function PipelineRail({ stages, compact = false }: { stages: Stage[]; compact?: boolean }) {
  return (
    <ol className="relative flex flex-col gap-0" role="list">
      {/* The spine. Sits behind the nodes and stops one node short at each
          end so it never pokes out past the first and last dots. */}
      <span
        aria-hidden="true"
        className="absolute left-[11px] top-3 bottom-3 w-px bg-gradient-to-b from-accent/40 via-border-strong to-accent/10"
      />
      {stages.map((stage, i) => (
        <li key={stage.key} className={cn("relative flex items-center gap-3.5", compact ? "py-2" : "py-2.5")}>
          <span className="relative z-10 flex h-[23px] w-[23px] flex-none items-center justify-center rounded-full border border-border-strong bg-surface">
            <Icon name={stage.icon} size={11} className="text-accent-text" />
          </span>
          <span
            aria-hidden="true"
            className="lp-flow-dot pointer-events-none absolute left-[8.5px] top-1/2 h-1.5 w-1.5 rounded-full bg-accent"
            style={{ animationDelay: `${i * 0.32}s` }}
          />
          <span className="min-w-0">
            <span className="block text-caption font-medium text-ink">{stage.label}</span>
            {!compact && <span className="block text-micro text-ink-faint">{stage.plain}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

/* ----------------------------------------------------------------- card -- */

/** A card that borrows the product's own definition: a border, not a fill.
 *  Fill means hover or selection there, and it should mean the same here. */
export function GlassCard({
  children,
  className,
  interactive = false,
}: {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-surface",
        interactive &&
          "transition-colors duration-300 hover:border-border-strong motion-safe:hover:-translate-y-0.5 motion-safe:transition-[transform,border-color]",
        className,
      )}
    >
      {children}
    </div>
  );
}
