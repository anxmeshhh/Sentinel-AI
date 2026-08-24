import { Badge, Icon } from "../ui";
import { Reveal } from "./Reveal";
import { PIPELINE, Section, SectionHeading } from "./primitives";

/**
 * The Core as a story, not a flowchart.
 *
 * The plain sentence leads and the Sentinel term sits under it as a label:
 * someone skimming reads eight short sentences that make sense on their own,
 * and someone technical reads the actual architecture. Neither reader has to
 * decode the other's version.
 *
 * Stages reveal in sequence as they enter the viewport, which is the one
 * place a stagger earns itself here - the delay IS the pipeline.
 */
const DETERMINISTIC = new Set(["signals", "findings", "situations", "memory", "decisions", "actions"]);

export function HowItThinks() {
  return (
    <Section id="how">
      <SectionHeading
        eyebrow="How Sentinel thinks"
        title="Eight steps, and only one of them guesses."
        lede="Each layer hands the next something more useful than it received. The model is reached in two places, and in both it is given a conclusion that has already been computed and asked to put it into words."
      />

      <ol className="relative">
        {/* One continuous spine behind every step. */}
        <span
          aria-hidden="true"
          className="absolute left-[19px] top-4 bottom-8 w-px bg-gradient-to-b from-accent/40 via-border-strong to-transparent sm:left-[23px]"
        />

        {PIPELINE.map((stage, i) => (
          <Reveal as="li" key={stage.key} delay={i * 60} className="relative flex gap-5 pb-9 last:pb-0 sm:gap-7">
            <span className="relative z-10 flex h-10 w-10 flex-none items-center justify-center rounded-full border border-border-strong bg-surface sm:h-12 sm:w-12">
              <Icon name={stage.icon} size={16} className="text-accent-text" />
            </span>

            <div className="min-w-0 flex-1 pt-1">
              <p className="text-[clamp(16px,2vw,20px)] font-medium leading-snug text-ink">{stage.plain}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="font-mono text-micro uppercase tracking-[0.14em] text-ink-faint">
                  {stage.label}
                </span>
                <Badge tone={DETERMINISTIC.has(stage.key) ? "good" : "accent"}>
                  {DETERMINISTIC.has(stage.key) ? "Deterministic" : "Explained by the model"}
                </Badge>
              </div>
            </div>
          </Reveal>
        ))}
      </ol>

      <Reveal delay={120}>
        <div className="mt-12 rounded-lg border border-border bg-surface p-6 sm:mt-16 sm:p-7">
          <p className="text-[clamp(15px,1.7vw,17px)] leading-relaxed text-ink-dim">
            <span className="text-ink">Severity, priority, progress and goal health are arithmetic.</span>{" "}
            They are written before any model is called, and every one of them carries a reason you can
            check. That is why a verdict here can be argued with — there is something underneath it to
            argue about.
          </p>
        </div>
      </Reveal>
    </Section>
  );
}
