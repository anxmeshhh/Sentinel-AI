import { useEffect, useState } from "react";

import { Badge, Icon } from "../ui";
import { prefersReducedMotion, Reveal, useRevealed } from "./Reveal";
import { GlassCard, Section, SectionHeading } from "./primitives";

/**
 * The Assistant, shown doing only things it can actually do.
 *
 * Three exchanges, each mapping to a real capability: catch-up, an
 * investigation grounded in evidence, and a verified action. Nothing here
 * claims a capability the product does not have - the temptation on a landing
 * page is to script the assistant you wish you had built, and a visitor who
 * signs up and finds a different one has been misled rather than persuaded.
 *
 * The turns appear in sequence once visible, then stop.
 */
interface Turn {
  role: "user" | "sentinel";
  text?: string;
  evidence?: string[];
  verdict?: { label: string; tone: "good" | "crit" | "warn" };
  note?: string;
}

const TURNS: Turn[] = [
  { role: "user", text: "What did I miss?" },
  {
    role: "sentinel",
    text: "Since Friday: 4 flagged emails went unanswered, a review queue built up on one person, and a situation around payments-service formed again.",
    note: "Catch-up · covers the gap since you were last here",
  },
  { role: "user", text: "What should I do about the stalled PR?" },
  {
    role: "sentinel",
    text: "It has been open 9 days with two reviewers assigned and no review submitted. The same repository shows up in an open situation with a Slack blocker.",
    evidence: ["GitHub · PR #482 open 9 days", "Slack · #payments flagged as blocked", "Memory · seen 3 times"],
    verdict: { label: "Recommended: spread the review load", tone: "warn" },
    note: "Investigation · evidence retrieved, then explained",
  },
  { role: "user", text: "Snooze it until tomorrow." },
  {
    role: "sentinel",
    verdict: { label: "Snoozed until tomorrow", tone: "good" },
    note: "Verified · read back and confirmed",
  },
];

export function AssistantDemo() {
  const { ref, revealed } = useRevealed<HTMLDivElement>();
  const [shown, setShown] = useState(prefersReducedMotion() ? TURNS.length : 0);

  useEffect(() => {
    if (!revealed || prefersReducedMotion()) return;
    const timers = TURNS.map((_, i) => window.setTimeout(() => setShown(i + 1), 300 + i * 900));
    return () => timers.forEach(window.clearTimeout);
  }, [revealed]);

  return (
    <Section id="assistant">
      <SectionHeading
        eyebrow="The Assistant"
        title="Ask in the way you'd ask a colleague."
        lede="Routine questions are answered from what Sentinel already computed — no model involved, no waiting. The model is reached only when the question is genuinely open-ended, and never more than once."
      />

      <Reveal>
        <GlassCard className="overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-rule px-5 py-3.5">
            <div className="flex items-center gap-2">
              <Icon name="sparkle" size={14} className="text-accent-text" />
              <span className="text-caption font-medium text-ink">Assistant</span>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-micro text-ink-dim">
              <Icon name="user" size={11} /> Personal
            </span>
          </div>

          <div ref={ref} className="flex min-h-[440px] flex-col gap-4 p-5 sm:min-h-[400px] sm:p-6">
            {TURNS.slice(0, shown).map((turn, i) =>
              turn.role === "user" ? (
                <div key={i} className="lp-reveal lp-in flex justify-end">
                  <p className="max-w-[80%] rounded-lg rounded-br-sm bg-surface-2 px-3.5 py-2 text-small text-ink">
                    {turn.text}
                  </p>
                </div>
              ) : (
                <div key={i} className="lp-reveal lp-in flex gap-2.5">
                  <span className="mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-full border border-accent/40 bg-accent/10">
                    <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                  </span>
                  <div className="min-w-0 flex-1">
                    {turn.text && (
                      <p className="text-small leading-relaxed text-ink-dim">{turn.text}</p>
                    )}

                    {turn.evidence && (
                      <ul className="mt-3 flex flex-col gap-1.5">
                        {turn.evidence.map((e) => (
                          <li
                            key={e}
                            className="flex items-center gap-2 rounded-md border border-border bg-surface-2/50 px-3 py-1.5 text-micro text-ink-dim"
                          >
                            <span className="h-1 w-1 flex-none rounded-full bg-ink-faint" />
                            {e}
                          </li>
                        ))}
                      </ul>
                    )}

                    {turn.verdict && (
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <Badge tone={turn.verdict.tone}>{turn.verdict.label}</Badge>
                      </div>
                    )}

                    {turn.note && <p className="mt-2 text-micro text-ink-faint">{turn.note}</p>}
                  </div>
                </div>
              ),
            )}

            {shown < TURNS.length && (
              <span className="inline-flex items-center gap-2 text-caption text-ink-faint">
                <span className="lp-pulse h-1.5 w-1.5 rounded-full bg-accent" />
                Reading the Core…
              </span>
            )}
          </div>

          {/* The composer, rendered as the real one looks - inert here. */}
          <div className="border-t border-rule px-5 py-4">
            <div className="flex items-center gap-3 rounded-lg border border-border bg-surface-2/40 px-3.5 py-2.5">
              <span className="flex-1 text-small text-ink-faint">
                Ask Sentinel anything
                <span className="lp-caret ml-0.5 inline-block h-[14px] w-px translate-y-[2px] bg-ink-faint" />
              </span>
              <span className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-accent/80">
                <Icon name="send" size={12} className="text-white" />
              </span>
            </div>
          </div>
        </GlassCard>
      </Reveal>
    </Section>
  );
}
