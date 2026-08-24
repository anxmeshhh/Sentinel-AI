import { useEffect, useState } from "react";

import { Badge, Icon, type IconName } from "../ui";
import { cn } from "../ui/cn";
import { prefersReducedMotion, Reveal, useRevealed } from "./Reveal";
import { GlassCard, Section, SectionHeading } from "./primitives";

/**
 * The real product, one state at a time.
 *
 * Built from the same primitives the application uses - Badge, Icon, the card
 * border, the severity tones - so this reads as a window onto Sentinel rather
 * than a marketing mock of it. The five states follow the path a person
 * actually takes: see it, open it, understand it, act, confirm.
 *
 * Auto-advances once in view, and a click takes over from the timer - if
 * someone reaches for a tab, the page should stop moving under them.
 */
type StateKey = "dashboard" | "situation" | "investigation" | "action" | "verified";

const STATES: { key: StateKey; label: string; icon: IconName }[] = [
  { key: "dashboard", label: "Attention", icon: "activity" },
  { key: "situation", label: "Situation", icon: "layers" },
  { key: "investigation", label: "Investigation", icon: "search" },
  { key: "action", label: "Action", icon: "flag" },
  { key: "verified", label: "Verified", icon: "check" },
];

export function ProductShowcase() {
  const { ref, revealed } = useRevealed<HTMLDivElement>();
  const [active, setActive] = useState<StateKey>("dashboard");
  const [manual, setManual] = useState(prefersReducedMotion());

  useEffect(() => {
    if (!revealed || manual || prefersReducedMotion()) return;
    const timers = STATES.map((s, i) => window.setTimeout(() => setActive(s.key), 900 + i * 2300));
    return () => timers.forEach(window.clearTimeout);
  }, [revealed, manual]);

  return (
    <Section id="product">
      <SectionHeading
        eyebrow="The product"
        title="This is the actual interface."
        lede="Not a mockup drawn for a website. The same components, tones and typography the application ships with — because the fastest way to lose trust is for the product to look nothing like the page that sold it."
      />

      <Reveal>
        <div ref={ref}>
          {/* State switcher, doubling as the story: see -> open -> understand
              -> act -> confirm. */}
          <div className="scroll-x mb-4 flex gap-1.5 border-b border-border pb-3">
            {STATES.map((s) => (
              <button
                key={s.key}
                type="button"
                onClick={() => {
                  setManual(true);
                  setActive(s.key);
                }}
                className={cn(
                  "inline-flex flex-none items-center gap-1.5 rounded-md px-3 py-1.5 text-caption transition-colors duration-200",
                  active === s.key
                    ? "bg-surface-2 font-medium text-ink"
                    : "text-ink-faint hover:text-ink-dim",
                )}
              >
                <Icon name={s.icon} size={12} />
                {s.label}
              </button>
            ))}
          </div>

          <GlassCard className="min-h-[340px] p-5 sm:min-h-[320px] sm:p-6">
            {active === "dashboard" && <StateDashboard />}
            {active === "situation" && <StateSituation />}
            {active === "investigation" && <StateInvestigation />}
            {active === "action" && <StateAction />}
            {active === "verified" && <StateVerified />}
          </GlassCard>
        </div>
      </Reveal>
    </Section>
  );
}

function Row({
  tone,
  icon,
  title,
  meta,
  badge,
}: {
  tone: string;
  icon: IconName;
  title: string;
  meta: string;
  badge?: { label: string; tone: "crit" | "warn" | "high" | "good" };
}) {
  return (
    <div className="flex items-start gap-3 px-1 py-3">
      <span className={cn("mt-[9px] h-1.5 w-1.5 flex-none rounded-full", tone)} />
      <span className="mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-md border border-border bg-surface-2 text-ink-faint">
        <Icon name={icon} size={14} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-small font-medium leading-snug text-ink">{title}</span>
        <span className="mt-1 flex flex-wrap items-center gap-2">
          <span className="text-micro text-ink-faint">{meta}</span>
          {badge && <Badge tone={badge.tone}>{badge.label}</Badge>}
        </span>
      </span>
    </div>
  );
}

function StateDashboard() {
  return (
    <div className="lp-reveal lp-in">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="text-caption font-semibold text-ink">Attention</span>
        <span className="text-micro text-ink-faint">3 open</span>
      </div>
      <div className="divide-y divide-rule rounded-lg border border-border">
        <Row
          tone="bg-crit"
          icon="layers"
          title="GitHub and Slack activity around payments-service keeps coming up together"
          meta="3 related findings · 2 services"
          badge={{ label: "Critical", tone: "crit" }}
        />
        <Row
          tone="bg-warn"
          icon="calendar"
          title="Double-booked: Design review overlaps 1:1"
          meta="30 minute overlap tomorrow"
          badge={{ label: "Review", tone: "warn" }}
        />
        <Row
          tone="bg-high"
          icon="mail"
          title="4 important emails are still unanswered"
          meta="Flagged, unread for 3+ days"
        />
      </div>
    </div>
  );
}

function StateSituation() {
  return (
    <div className="lp-reveal lp-in">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Badge tone="crit">Critical</Badge>
        <Badge tone="outline">GitHub</Badge>
        <Badge tone="outline">Slack</Badge>
        <span className="text-micro text-ink-faint">seen 3×</span>
      </div>
      <h3 className="text-[clamp(17px,2.4vw,22px)] font-semibold tracking-[-0.02em] text-ink">
        payments-service
      </h3>
      <p className="mt-2 text-small leading-relaxed text-ink-dim">
        GitHub and Slack activity around payments-service keeps coming up together.
      </p>
      <div className="mt-5 grid gap-2 sm:grid-cols-3">
        {[
          { k: "Findings", v: "3" },
          { k: "Providers", v: "2" },
          { k: "First seen", v: "9 days ago" },
        ].map((s) => (
          <div key={s.k} className="rounded-md border border-border bg-surface-2/50 px-3 py-2.5">
            <span className="block text-micro text-ink-faint">{s.k}</span>
            <span className="block text-small font-medium text-ink">{s.v}</span>
          </div>
        ))}
      </div>
      <p className="mt-4 border-t border-rule pt-4 text-micro leading-relaxed text-ink-faint">
        Correlated because three findings point at the same repository — not because they looked
        similar.
      </p>
    </div>
  );
}

function StateInvestigation() {
  return (
    <div className="lp-reveal lp-in">
      <span className="label-sub">Investigation</span>
      <p className="mt-3 text-small leading-relaxed text-ink-dim">
        A pull request has been open nine days with two reviewers assigned and no review submitted.
        The same repository has a blocker flagged in Slack, and this pattern has formed before.
      </p>
      <div className="mt-5">
        <span className="label-sub">Evidence</span>
        <ul className="mt-2 flex flex-col gap-1.5">
          {[
            "GitHub · PR #482 open 9 days, 2 reviewers requested",
            "Slack · #payments flagged as blocked",
            "Memory · this situation has recurred 3 times",
          ].map((e) => (
            <li
              key={e}
              className="flex items-center gap-2 rounded-md border border-border bg-surface-2/50 px-3 py-2 text-micro text-ink-dim"
            >
              <span className="h-1 w-1 flex-none rounded-full bg-ink-faint" />
              {e}
            </li>
          ))}
        </ul>
      </div>
      <p className="mt-4 border-t border-rule pt-4 text-micro leading-relaxed text-ink-faint">
        The reading is generated. The evidence is retrieved from your connected data, not generated.
      </p>
    </div>
  );
}

function StateAction() {
  return (
    <div className="lp-reveal lp-in">
      <div className="rounded-lg border border-accent/30 bg-accent/[0.05] p-5">
        <p className="text-micro font-semibold uppercase tracking-[0.12em] text-ink-faint">
          Proposed action
        </p>
        <p className="mt-2 text-small font-semibold text-ink">Snooze this item</p>
        <dl className="mt-3 flex flex-col gap-1.5">
          <div className="flex gap-3">
            <dt className="w-20 flex-none text-micro text-ink-faint">For</dt>
            <dd className="text-caption text-ink">24 hours</dd>
          </div>
          <div className="flex gap-3">
            <dt className="w-20 flex-none text-micro text-ink-faint">Effect</dt>
            <dd className="text-caption text-ink-dim">
              Hides it from your attention list until then. Reversible.
            </dd>
          </div>
        </dl>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-caption font-medium text-accent-ink">
            <Icon name="check" size={12} /> Confirm
          </span>
          <span className="inline-flex items-center rounded-md px-3 py-1.5 text-caption text-ink-faint">
            Cancel
          </span>
        </div>
      </div>
      <p className="mt-4 text-micro leading-relaxed text-ink-faint">
        The server decided this needed showing before it ran. The client cannot skip that.
      </p>
    </div>
  );
}

function StateVerified() {
  return (
    <div className="lp-reveal lp-in flex min-h-[240px] flex-col items-center justify-center text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full border border-good/40 bg-good/10">
        <Icon name="check" size={20} className="text-good" />
      </span>
      <p className="mt-4 text-[clamp(16px,2vw,19px)] font-medium text-ink">Snoozed until tomorrow</p>
      <p className="mt-2 max-w-[38ch] text-caption leading-relaxed text-ink-dim">
        Read back from the record and confirmed. Recorded as an action you can undo, with who asked
        and what they were shown.
      </p>
      <div className="mt-4 flex items-center gap-2">
        <Badge tone="good">Verified</Badge>
        <span className="text-micro text-ink-faint">View activity</span>
      </div>
    </div>
  );
}
