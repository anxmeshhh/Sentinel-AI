import { useEffect, useState } from "react";

import { Badge, Icon, type IconName } from "../ui";
import { cn } from "../ui/cn";
import { prefersReducedMotion, Reveal, useRevealed } from "./Reveal";
import { GlassCard, Section, SectionHeading } from "./primitives";

/**
 * The section that separates Sentinel from an assistant that answers questions.
 *
 * The six steps advance on a timer once the block is in view, and stop at the
 * end - it plays once, like a demonstration, rather than looping like an
 * advert. Under reduced motion the finished state renders immediately, which
 * is the whole story anyway.
 *
 * Every step named here is a real stage in the Action Registry:
 * propose -> validate -> authorize -> preview -> execute -> verify.
 */
const STEPS: { key: string; label: string; detail: string; icon: IconName }[] = [
  { key: "observe", label: "Observe", detail: "The item is already on screen", icon: "activity" },
  { key: "understand", label: "Understand", detail: '"this" resolves to that item — no model needed', icon: "search" },
  { key: "plan", label: "Plan", detail: "attention.snooze, 24 hours", icon: "flag" },
  { key: "confirm", label: "Confirm", detail: "The server decides if a person must approve", icon: "lock" },
  { key: "act", label: "Act", detail: "Executed through the Action Registry", icon: "sparkle" },
  { key: "verify", label: "Verify", detail: "Read back and confirmed", icon: "check" },
];

export function Agentic() {
  const { ref, revealed } = useRevealed<HTMLDivElement>();
  const [step, setStep] = useState(prefersReducedMotion() ? STEPS.length : -1);

  useEffect(() => {
    if (!revealed || prefersReducedMotion()) return;
    // Advances once and stops. A looping demo is something the reader has to
    // wait out; a single pass is something they watch.
    const timers = STEPS.map((_, i) => window.setTimeout(() => setStep(i), 420 + i * 620));
    return () => timers.forEach(window.clearTimeout);
  }, [revealed]);

  const done = step >= STEPS.length - 1;

  return (
    <Section id="agentic">
      <SectionHeading
        eyebrow="Not just an assistant"
        title="Most assistants answer. This one operates."
        lede="Asking a model a question is easy. Letting it touch your calendar is not — so it cannot. Sentinel proposes; the server decides what needs confirming; the registry executes and then reads the result back to check it actually happened."
      />

      <div ref={ref} className="grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:gap-10">
        {/* The request, as a person would type it. */}
        <Reveal>
          <GlassCard className="p-5 sm:p-6">
            <span className="label-sub">In the Assistant</span>
            <div className="mt-4 flex justify-end">
              <p className="max-w-[85%] rounded-lg rounded-br-sm bg-surface-2 px-3.5 py-2 text-small text-ink">
                Snooze this until tomorrow.
              </p>
            </div>

            <div className="mt-5 flex gap-2.5">
              <span className="mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-full border border-accent/40 bg-accent/10">
                <span className="h-1.5 w-1.5 rounded-full bg-accent" />
              </span>
              <div className="min-w-0 flex-1">
                {done ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="good">Snoozed until tomorrow</Badge>
                    <span className="text-micro text-ink-faint">Verified</span>
                  </div>
                ) : (
                  <span className="inline-flex items-center gap-2 text-caption text-ink-faint">
                    <span className="lp-pulse h-1.5 w-1.5 rounded-full bg-accent" />
                    Reading the Core…
                  </span>
                )}
              </div>
            </div>

            <p className="mt-6 border-t border-rule pt-4 text-micro leading-relaxed text-ink-faint">
              Zero model calls. The target was on screen and the verb was unambiguous, so there was
              nothing left to interpret.
            </p>
          </GlassCard>
        </Reveal>

        {/* What happened underneath. */}
        <Reveal delay={100}>
          <GlassCard className="p-5 sm:p-6">
            <span className="label-sub">Underneath</span>
            <ol className="mt-4 flex flex-col gap-0" role="list">
              {STEPS.map((s, i) => {
                const active = i <= step;
                return (
                  <li key={s.key} className="relative flex gap-3.5 pb-4 last:pb-0">
                    {i < STEPS.length - 1 && (
                      <span
                        aria-hidden="true"
                        className={cn(
                          "absolute left-[13px] top-7 h-full w-px transition-colors duration-500",
                          active ? "bg-accent/40" : "bg-rule",
                        )}
                      />
                    )}
                    <span
                      className={cn(
                        "relative z-10 flex h-[27px] w-[27px] flex-none items-center justify-center rounded-full border transition-all duration-500",
                        active
                          ? "border-accent/50 bg-accent/10 text-accent-text"
                          : "border-border bg-surface text-ink-faint",
                      )}
                    >
                      <Icon name={s.icon} size={12} />
                    </span>
                    <span className="min-w-0 pt-0.5">
                      <span
                        className={cn(
                          "block text-caption font-medium transition-colors duration-500",
                          active ? "text-ink" : "text-ink-faint",
                        )}
                      >
                        {s.label}
                      </span>
                      <span className="block text-micro text-ink-faint">{s.detail}</span>
                    </span>
                  </li>
                );
              })}
            </ol>
          </GlassCard>
        </Reveal>
      </div>

      <Reveal delay={160}>
        <p className="mt-8 max-w-[62ch] text-caption leading-relaxed text-ink-faint">
          A model that can call provider APIs decides its own permissions: whatever it can phrase, it
          can attempt. Here it can only name an action that already exists, with parameters a schema
          has to accept — so the worst a poisoned email can achieve is proposing something you then
          see, preview, and decline.
        </p>
      </Reveal>
    </Section>
  );
}
