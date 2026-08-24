import { Link } from "react-router-dom";

import { Icon } from "../ui";
import { Reveal } from "./Reveal";
import { GlassCard, PIPELINE, PipelineRail } from "./primitives";

/**
 * The first screen. It has ten seconds to answer "what is this".
 *
 * So the headline states the problem and the resolution in one breath, and
 * the visual beside it is the actual pipeline rather than an abstract
 * illustration - by the time someone reaches "How Sentinel thinks" they have
 * already seen its shape once.
 */
export function Hero() {
  return (
    <header className="relative overflow-hidden">
      {/* A single wide, very dim purple wash. Not a glowing blob: it sits at
          4% and exists only to stop the top of the page reading as a flat
          black rectangle. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 -top-40 h-[520px] bg-[radial-gradient(ellipse_60%_50%_at_50%_0%,rgba(99,102,241,0.10),transparent_70%)]"
      />

      <div className="relative mx-auto w-full max-w-6xl px-5 pb-20 pt-20 sm:px-8 sm:pb-28 sm:pt-28">
        <div className="grid items-center gap-14 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)] lg:gap-20">
          <div>
            <Reveal>
              <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-micro text-ink-dim">
                <span className="lp-pulse h-1.5 w-1.5 rounded-full bg-accent" />
                Operations intelligence
              </span>
            </Reveal>

            <Reveal delay={80}>
              <h1 className="mt-6 text-[clamp(34px,6.2vw,60px)] font-semibold leading-[1.05] tracking-[-0.035em] text-ink">
                Your work is scattered.
                <br />
                <span className="text-ink-dim">Sentinel makes sense of it.</span>
              </h1>
            </Reveal>

            <Reveal delay={160}>
              <p className="mt-6 max-w-[56ch] text-[clamp(15px,1.7vw,18px)] leading-relaxed text-ink-dim">
                Sentinel connects the information already spread across your work tools, works out
                what actually matters, and helps you decide what to do next — then does it, once
                you say yes.
              </p>
            </Reveal>

            <Reveal delay={240}>
              <div className="mt-9 flex flex-wrap items-center gap-3">
                <Link
                  to="/login"
                  className="group inline-flex items-center justify-center gap-2 rounded-md bg-accent px-5 py-3 text-small font-medium text-accent-ink transition-colors duration-200 hover:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  Explore Sentinel
                  <Icon
                    name="arrowRight"
                    size={14}
                    className="transition-transform duration-200 motion-safe:group-hover:translate-x-0.5"
                  />
                </Link>
                <a
                  href="#how"
                  className="inline-flex items-center justify-center gap-2 rounded-md border border-border px-5 py-3 text-small font-medium text-ink-dim transition-colors duration-200 hover:border-border-strong hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  See how it works
                </a>
              </div>
            </Reveal>

            <Reveal delay={320}>
              <p className="mt-8 text-micro leading-relaxed text-ink-faint">
                Detection is deterministic. The model explains, it never decides.
              </p>
            </Reveal>
          </div>

          {/* The pipeline, stated once, early. On mobile it drops below the
              copy rather than shrinking beside it. */}
          <Reveal delay={200}>
            <GlassCard className="p-6 sm:p-7">
              <div className="mb-5 flex items-center justify-between gap-3">
                <span className="label-sub">The Core</span>
                <span className="text-micro text-ink-faint">one pipeline</span>
              </div>
              <PipelineRail stages={PIPELINE} compact />
              <p className="mt-5 border-t border-rule pt-4 text-micro leading-relaxed text-ink-faint">
                Every domain runs through this. There is no second engine for any provider.
              </p>
            </GlassCard>
          </Reveal>
        </div>
      </div>
    </header>
  );
}
