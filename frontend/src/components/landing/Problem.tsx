import {
  CalendarIcon,
  DriveIcon,
  GitHubIcon,
  GoogleIcon,
  MailIcon,
  MicrosoftIcon,
  SlackIcon,
  ZoomIcon,
} from "../ProviderIcons";
import { Reveal } from "./Reveal";
import { Section, SectionHeading } from "./primitives";

/**
 * The problem, shown rather than argued.
 *
 * Eight real provider marks drift inward toward one point. The animation is
 * the claim: these are not eight problems, they are one, and the only thing
 * missing is something looking across them.
 *
 * The marks are the same components the product's own Connections page uses,
 * so this is a picture of what Sentinel actually reads - not stock logos.
 */
const SIGNALS = [
  { Glyph: GitHubIcon, label: "GitHub", x: -230, y: -96, delay: 0 },
  { Glyph: MailIcon, label: "Gmail", x: 226, y: -110, delay: 0.7 },
  { Glyph: CalendarIcon, label: "Calendar", x: -272, y: 44, delay: 1.4 },
  { Glyph: SlackIcon, label: "Slack", x: 258, y: 52, delay: 2.1 },
  { Glyph: DriveIcon, label: "Drive", x: -150, y: 128, delay: 2.8 },
  { Glyph: MicrosoftIcon, label: "Microsoft 365", x: 158, y: 136, delay: 3.5 },
  { Glyph: ZoomIcon, label: "Zoom", x: -60, y: -150, delay: 4.2 },
  { Glyph: GoogleIcon, label: "Google", x: 74, y: -156, delay: 4.9 },
];

export function Problem() {
  return (
    <Section id="problem">
      <SectionHeading
        eyebrow="The problem"
        title={
          <>
            Your work already contains the answers.
            <br />
            <span className="text-ink-dim">They&rsquo;re just scattered.</span>
          </>
        }
        lede="A stalled review in one tool, the deadline it threatens in another, the conversation about it in a third. Each tool shows you its own corner. Nothing looks across them — which is exactly where the things that go wrong live."
      />

      <Reveal>
        <div className="relative mx-auto h-[300px] w-full max-w-3xl overflow-hidden sm:h-[380px]">
          {/* The drifting signals. Hidden below sm: eight absolutely
              positioned marks cannot be made legible on a 360px screen, and
              a cramped version of this says less than the honest list does. */}
          <div className="absolute inset-0 hidden items-center justify-center sm:flex">
            {SIGNALS.map(({ Glyph, label, x, y, delay }) => (
              <span
                key={label}
                aria-hidden="true"
                className="lp-converge absolute flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-surface"
                style={
                  {
                    "--lp-x": `${x}px`,
                    "--lp-y": `${y}px`,
                    animationDelay: `${delay}s`,
                  } as React.CSSProperties
                }
              >
                <span className="flex h-4 w-4 items-center justify-center">
                  <Glyph />
                </span>
              </span>
            ))}

            {/* The Core. Static, because it is the thing everything else
                moves toward - if it moved too, nothing would read as centre. */}
            <div className="relative flex h-28 w-28 items-center justify-center rounded-full border border-accent/30 bg-surface">
              <span
                aria-hidden="true"
                className="lp-pulse absolute inset-0 rounded-full bg-[radial-gradient(circle,rgba(99,102,241,0.16),transparent_70%)]"
              />
              <span className="relative text-center">
                <span className="block text-caption font-semibold text-ink">Sentinel</span>
                <span className="block text-micro text-ink-faint">one Core</span>
              </span>
            </div>
          </div>

          {/* Mobile: the same idea, recomposed as a list rather than a
              shrunken diagram. */}
          <div className="flex h-full flex-col items-center justify-center gap-5 sm:hidden">
            <ul className="grid w-full grid-cols-2 gap-2">
              {SIGNALS.slice(0, 6).map(({ Glyph, label }) => (
                <li
                  key={label}
                  className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2"
                >
                  <span className="flex h-4 w-4 flex-none items-center justify-center">
                    <Glyph />
                  </span>
                  <span className="truncate text-micro text-ink-dim">{label}</span>
                </li>
              ))}
            </ul>
            <span aria-hidden="true" className="h-8 w-px bg-gradient-to-b from-border-strong to-accent/40" />
            <div className="flex h-20 w-20 items-center justify-center rounded-full border border-accent/30 bg-surface text-center">
              <span>
                <span className="block text-caption font-semibold text-ink">Sentinel</span>
                <span className="block text-micro text-ink-faint">one Core</span>
              </span>
            </div>
          </div>
        </div>
      </Reveal>
    </Section>
  );
}
