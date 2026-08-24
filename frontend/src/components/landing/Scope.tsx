import { Icon } from "../ui";
import { Reveal } from "./Reveal";
import { GlassCard, Section, SectionHeading } from "./primitives";

/**
 * Privacy as architecture rather than a promise.
 *
 * The claim worth making here is precise, so it is made precisely: a group
 * scope cannot read personal data - not "is filtered so it doesn't", cannot,
 * because the set of connections it is given never contains them. And the
 * availability example is the strongest version of that: the function that
 * combines calendars returns times and has no field for a title, so it is
 * incapable of leaking one.
 */
export function Scope() {
  return (
    <Section id="scope">
      <SectionHeading
        eyebrow="Personal + Group"
        title="It can use both. It cannot expose either."
        lede="Personal and group intelligence are the same engines run with a different scope. An engine only ever sees the set of connections it was handed — which is why the boundary is a property of the data rather than a rule someone has to remember."
      />

      <div className="grid gap-3 md:grid-cols-2">
        <Reveal>
          <GlassCard className="h-full p-6">
            <div className="mb-4 flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-md border border-ctx-personal/40 bg-ctx-personal/10">
                <Icon name="user" size={14} className="text-ctx-personal" />
              </span>
              <span className="text-caption font-semibold uppercase tracking-[0.12em] text-ink-dim">
                Personal
              </span>
            </div>
            <p className="text-small leading-relaxed text-ink-dim">
              The accounts you connected yourself. Your mail, your calendar, your files, your tasks.
            </p>
            <p className="mt-3 text-caption leading-relaxed text-ink-faint">
              Connecting a service shares it nowhere by itself.
            </p>
          </GlassCard>
        </Reveal>

        <Reveal delay={80}>
          <GlassCard className="h-full p-6">
            <div className="mb-4 flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-md border border-ctx-org/40 bg-ctx-org/10">
                <Icon name="grid" size={14} className="text-accent-text" />
              </span>
              <span className="text-caption font-semibold uppercase tracking-[0.12em] text-ink-dim">
                Group
              </span>
            </div>
            <p className="text-small leading-relaxed text-ink-dim">
              What an organisation deliberately shared — with a workspace, a class, a group, or one
              channel.
            </p>
            <p className="mt-3 text-caption leading-relaxed text-ink-faint">
              Authorization is re-checked on the server for every request.
            </p>
          </GlassCard>
        </Reveal>
      </div>

      {/* The combine-without-exposing case, which is the interesting one. */}
      <Reveal delay={140}>
        <GlassCard className="mt-3 overflow-hidden">
          <div className="border-b border-rule px-6 py-4">
            <span className="label-sub">Combining, without disclosing</span>
          </div>
          <div className="grid gap-0 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
            <div className="p-6">
              <p className="text-caption text-ink-faint">Sentinel reads</p>
              <p className="mt-2 text-small leading-relaxed text-ink-dim">
                Your private calendar <span className="text-ink-faint">and</span> the team&rsquo;s
                shared one, together, to find a time that genuinely works.
              </p>
            </div>

            <div className="flex items-center justify-center px-6 py-2 md:py-6">
              <Icon name="arrowRight" size={16} className="hidden text-ink-faint md:block" />
              <Icon name="chevronDown" size={16} className="text-ink-faint md:hidden" />
            </div>

            <div className="p-6">
              <p className="text-caption text-ink-faint">Sentinel says</p>
              <p className="mt-2 font-mono text-small leading-relaxed text-good">
                &ldquo;3 PM is unavailable.&rdquo;
              </p>
              <p className="mt-3 text-caption leading-relaxed text-ink-faint">
                Never <span className="text-ink-dim">whose</span> appointment it is. The function
                that finds free time returns start, end and minutes — there is no field for a title,
                so it cannot leak one.
              </p>
            </div>
          </div>
        </GlassCard>
      </Reveal>
    </Section>
  );
}
