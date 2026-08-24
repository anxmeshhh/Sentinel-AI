import { Badge, Icon } from "../ui";
import { Reveal } from "./Reveal";
import { GlassCard, Section, SectionHeading } from "./primitives";

/**
 * The two layers that make Sentinel more than a feed.
 *
 * Memory is what stops the same problem being reported at the same volume
 * forever; Goals is the only thing in the product that answers "will this
 * happen" rather than "what is true now".
 *
 * The line about the model not deciding goal health is the strongest
 * technical claim on the page, so it gets its own block rather than a
 * footnote.
 */
const MEMORY_STEPS = [
  { label: "A situation forms", detail: "findings correlate on one entity" },
  { label: "It resolves", detail: "the cluster stops qualifying" },
  { label: "It forms again", detail: "occurrence count reaches two" },
  { label: "Sentinel remembers", detail: "and raises the priority of anything matching" },
];

const GOAL_INPUTS = [
  { label: "Outcome", detail: "what done means, in your words" },
  { label: "Commitments", detail: "linked explicitly, each with a weight" },
  { label: "Situations", detail: "classified as a risk or a blocker by a person" },
  { label: "Deadline", detail: "how much time is actually left" },
];

export function MemoryGoals() {
  return (
    <Section id="memory">
      <SectionHeading
        eyebrow="Memory + Goals"
        title="It notices repetition. It measures outcomes."
        lede="Everything else in Sentinel answers what is true now. These two answer what keeps being true, and whether the thing you actually care about is going to happen."
      />

      <div className="grid gap-3 lg:grid-cols-2">
        <Reveal>
          <GlassCard className="h-full p-6">
            <div className="mb-5 flex items-center gap-2.5">
              <Icon name="brain" size={15} className="text-accent-text" />
              <span className="text-caption font-semibold uppercase tracking-[0.12em] text-ink-dim">
                Memory
              </span>
            </div>

            <ol className="flex flex-col gap-0" role="list">
              {MEMORY_STEPS.map((s, i) => (
                <li key={s.label} className="relative flex gap-3.5 pb-4 last:pb-0">
                  {i < MEMORY_STEPS.length - 1 && (
                    <span aria-hidden="true" className="absolute left-[7px] top-4 h-full w-px bg-rule" />
                  )}
                  <span className="relative z-10 mt-1.5 h-[15px] w-[15px] flex-none rounded-full border border-border-strong bg-surface" />
                  <span className="min-w-0">
                    <span className="block text-small text-ink">{s.label}</span>
                    <span className="block text-micro text-ink-faint">{s.detail}</span>
                  </span>
                </li>
              ))}
            </ol>

            <p className="mt-4 border-t border-rule pt-4 text-caption leading-relaxed text-ink-faint">
              And if it goes quiet for long enough, it is forgotten again — deliberately, so memory
              stays a record of what is live rather than everything that ever happened.
            </p>
          </GlassCard>
        </Reveal>

        <Reveal delay={80}>
          <GlassCard className="h-full p-6">
            <div className="mb-5 flex items-center gap-2.5">
              <Icon name="target" size={15} className="text-accent-text" />
              <span className="text-caption font-semibold uppercase tracking-[0.12em] text-ink-dim">
                Goals
              </span>
            </div>

            <ul className="grid gap-2 sm:grid-cols-2">
              {GOAL_INPUTS.map((g) => (
                <li key={g.label} className="rounded-md border border-border bg-surface-2/50 px-3 py-2.5">
                  <span className="block text-caption font-medium text-ink">{g.label}</span>
                  <span className="block text-micro leading-relaxed text-ink-faint">{g.detail}</span>
                </li>
              ))}
            </ul>

            <div className="mt-4 flex items-center gap-2 border-t border-rule pt-4">
              <Icon name="chevronDown" size={13} className="text-ink-faint" />
              <span className="text-caption text-ink-dim">computed health and progress</span>
              <Badge tone="crit">Blocked</Badge>
            </div>
            <p className="mt-3 text-caption leading-relaxed text-ink-faint">
              &ldquo;2 commitments are overdue and putting this goal at risk.&rdquo;
            </p>
          </GlassCard>
        </Reveal>
      </div>

      <Reveal delay={140}>
        <div className="mt-3 rounded-lg border border-accent/25 bg-accent/[0.04] p-6 sm:p-7">
          <p className="text-[clamp(15px,1.8vw,18px)] font-medium leading-relaxed text-ink">
            Sentinel does not let a language model decide whether a goal is healthy.
          </p>
          <p className="mt-3 max-w-[64ch] text-small leading-relaxed text-ink-dim">
            Health and progress are arithmetic over the work actually linked to it, written before
            any model is called. The model is handed the answer and asked to explain it — and when
            nothing is linked yet, progress reads{" "}
            <span className="text-ink">&ldquo;cannot yet be determined&rdquo;</span> rather than a
            confident zero.
          </p>
        </div>
      </Reveal>
    </Section>
  );
}
