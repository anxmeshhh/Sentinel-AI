import { Link } from "react-router-dom";

import { Icon, type IconName } from "../ui";
import { Reveal } from "./Reveal";
import { Section, SectionHeading } from "./primitives";

/**
 * Why Sentinel is different, stated as decisions rather than adjectives.
 *
 * No "AI-powered", no "next-generation". Each line below is a constraint the
 * codebase actually holds itself to, and most of them cost something to keep -
 * which is the only reason they are worth claiming.
 */
const PRINCIPLES: { icon: IconName; title: string; body: string }[] = [
  {
    icon: "check",
    title: "Evidence before explanation",
    body: "Every verdict carries the reasons that produced it. If you disagree, there is something underneath to disagree with.",
  },
  {
    icon: "activity",
    title: "Deterministic where it can be",
    body: "22 detectors, correlation, priority, health and progress are arithmetic over stored data. None of them calls a model.",
  },
  {
    icon: "sparkle",
    title: "The model explains, it never decides",
    body: "It is handed a conclusion that has already been computed and asked to phrase it. It cannot reorder what matters.",
  },
  {
    icon: "lock",
    title: "Permissions live on the server",
    body: "Scope is derived server-side and never accepted as a parameter. A group scope cannot read personal data — structurally, not by filter.",
  },
  {
    icon: "refresh",
    title: "Actions are verified",
    body: "Succeeded means executed and confirmed. When it ran but could not be confirmed, it says that instead of guessing.",
  },
  {
    icon: "layers",
    title: "One Core, not a fleet of agents",
    body: "Every domain runs through the same pipeline. There is no separate brain per provider to disagree with the others.",
  },
];

export function Principles() {
  return (
    <Section id="principles">
      <SectionHeading
        eyebrow="Why Sentinel"
        title="Decisions, not adjectives."
        lede="Most of these cost something to keep — they rule out shortcuts that would have shipped faster. That is what makes them worth stating."
      />

      <div className="grid gap-x-10 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
        {PRINCIPLES.map((p, i) => (
          <Reveal key={p.title} delay={i * 60}>
            <div className="border-t border-rule pt-5">
              <Icon name={p.icon} size={15} className="text-accent-text" />
              <h3 className="mt-3 text-small font-semibold text-ink">{p.title}</h3>
              <p className="mt-2 text-caption leading-relaxed text-ink-dim">{p.body}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </Section>
  );
}

/** The close. Confident, short, and not a sales pitch. */
export function FinalCta() {
  return (
    <Section className="pb-28 sm:pb-36">
      <Reveal>
        <div className="relative overflow-hidden rounded-xl border border-border bg-surface px-6 py-16 text-center sm:px-12 sm:py-20">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 -top-24 h-64 bg-[radial-gradient(ellipse_50%_60%_at_50%_0%,rgba(99,102,241,0.12),transparent_70%)]"
          />
          <div className="relative">
            <h2 className="mx-auto max-w-[22ch] text-[clamp(26px,4.4vw,42px)] font-semibold leading-[1.12] tracking-[-0.03em] text-ink">
              Your work is already telling you what matters.
            </h2>
            <p className="mx-auto mt-4 max-w-[46ch] text-[clamp(15px,1.7vw,17px)] leading-relaxed text-ink-dim">
              Sentinel helps you see it — and then helps you do something about it.
            </p>

            <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
              <Link
                to="/login"
                className="group inline-flex items-center justify-center gap-2 rounded-md bg-accent px-6 py-3 text-small font-medium text-accent-ink transition-colors duration-200 hover:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                Enter Sentinel
                <Icon
                  name="arrowRight"
                  size={14}
                  className="transition-transform duration-200 motion-safe:group-hover:translate-x-0.5"
                />
              </Link>
              <a
                href="https://github.com/anxmeshhh/Sentinel-AI"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center justify-center gap-2 rounded-md border border-border px-6 py-3 text-small font-medium text-ink-dim transition-colors duration-200 hover:border-border-strong hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                View on GitHub
                <Icon name="external" size={13} />
              </a>
            </div>
          </div>
        </div>
      </Reveal>
    </Section>
  );
}
