import { Badge, Icon, type IconName, type Tone } from "../ui";
import { Reveal } from "./Reveal";
import { GlassCard, Section, SectionHeading } from "./primitives";

/**
 * What Sentinel actually puts on screen.
 *
 * Every card below corresponds to a detector that exists: unanswered mail,
 * overdue commitments against a goal, a cross-provider situation, a calendar
 * conflict, a review queue, a recurring pattern. The wording is the product's
 * own - these are the sentences its engines generate, not marketing copy
 * written to sound like them.
 */
const CARDS: {
  tone: Tone;
  icon: IconName;
  badge: string;
  title: string;
  why: string;
  source: string;
}[] = [
  {
    tone: "warn",
    icon: "mail",
    badge: "Communication",
    title: "4 important emails are still unanswered",
    why: "Flagged and unread for more than three days — piling up rather than arriving",
    source: "Gmail",
  },
  {
    tone: "crit",
    icon: "target",
    badge: "Goals",
    title: "2 commitments are overdue and putting this goal at risk",
    why: "Health computed from linked work, not inferred — the goal reads BLOCKED",
    source: "Goals",
  },
  {
    tone: "crit",
    icon: "layers",
    badge: "Situation",
    title: "GitHub and Slack activity around payments-service keeps coming up together",
    why: "3 findings, one entity, two providers — correlated deterministically",
    source: "Cross-provider",
  },
  {
    tone: "warn",
    icon: "calendar",
    badge: "Meetings",
    title: "Double-booked: Design review overlaps 1:1",
    why: "30 minute overlap tomorrow — one of them needs moving",
    source: "Calendar",
  },
  {
    tone: "high",
    icon: "activity",
    badge: "Engineering",
    title: "5 pull requests waiting on one reviewer",
    why: "Review requests concentrated on a single person",
    source: "GitHub",
  },
  {
    tone: "good",
    icon: "brain",
    badge: "Memory",
    title: "This keeps recurring — seen 3 times",
    why: "A pattern that formed, resolved and formed again now raises priority",
    source: "Memory",
  },
];

export function Intelligence() {
  return (
    <Section id="intelligence">
      <SectionHeading
        eyebrow="What it surfaces"
        title="Facts, with the reason attached."
        lede="Nothing here is a summary of your inbox. Each one is a specific claim about something real, and each carries the evidence that produced it — so you can disagree with it."
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {CARDS.map((card, i) => (
          <Reveal key={card.title} delay={i * 70}>
            <GlassCard interactive className="h-full p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <span className="flex h-8 w-8 flex-none items-center justify-center rounded-md border border-border bg-surface-2">
                  <Icon name={card.icon} size={14} className="text-ink-faint" />
                </span>
                <Badge tone={card.tone}>{card.badge}</Badge>
              </div>
              <p className="text-small font-medium leading-snug text-ink">{card.title}</p>
              <p className="mt-2 text-caption leading-relaxed text-ink-dim">{card.why}</p>
              <p className="mt-3 border-t border-rule pt-3 text-micro text-ink-faint">{card.source}</p>
            </GlassCard>
          </Reveal>
        ))}
      </div>
    </Section>
  );
}
