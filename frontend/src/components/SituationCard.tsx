import { Link } from "react-router-dom";

import type { SituationRow } from "../api/types";
import { PROVIDER_GLYPH } from "./ProviderIcons";
import { relativeTime, severityOf } from "./situations";
import { Badge, Icon } from "./ui";

/** How many provider glyphs a card shows before folding the rest into "+N". */
const MAX_GLYPHS = 4;

/**
 * A Situation, compressed to what distinguishes it from every other one.
 *
 * How bad, what it's about, how much is behind it, when it last moved - four
 * facts, each its own visual weight, so the card is scanned rather than read.
 * The reasoning, evidence and recommendations already have a page; this
 * card's job is to get people there.
 */
export function SituationCard({ situation, compact = false }: { situation: SituationRow; compact?: boolean }) {
  const sev = severityOf(situation.severity);
  const providers = situation.providers;
  const heading = situation.entity ?? situation.title;
  // There is no separate prose explanation for a correlated situation - it is
  // a deterministic count of findings against a shared entity, not an LLM
  // summary. The backend's own `title` says the same thing as the chip row
  // below in words ("N related findings across gmail, google_calendar"),
  // raw provider ids included, so repeating it here would be both
  // redundant and a piece of internal terminology surfacing verbatim. The
  // chip row already carries this fact; a card with nothing distinct to add
  // in prose doesn't get a second line inventing one.

  if (compact) {
    return (
      <Link
        to={`/situations/${situation.id}`}
        className={`group flex items-center gap-3 rounded-md border border-l-2 border-border bg-transparent px-3 py-2.5 transition-colors hover:border-border-strong hover:bg-surface/50 ${sev.stripe}`}
      >
        <span className={`flex-none ${sev.text}`} aria-hidden="true">
          <Icon name={sev.icon} size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-small font-medium text-ink">{heading}</p>
          <p className="mt-0.5 truncate text-micro text-ink-faint">
            {situation.member_count} finding{situation.member_count === 1 ? "" : "s"}
            {providers.length > 0 && ` · ${providers.length} service${providers.length === 1 ? "" : "s"}`}
          </p>
        </div>
        <Icon name="external" size={13} className="flex-none text-ink-faint group-hover:text-ink" />
      </Link>
    );
  }

  return (
    <Link
      to={`/situations/${situation.id}`}
      className={`group flex flex-col gap-3 rounded-lg border border-l-2 border-border bg-surface px-4 py-4 transition-colors hover:border-border-strong hover:bg-surface/60 ${sev.stripe}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className={`flex h-9 w-9 flex-none items-center justify-center rounded-md ${sev.bg} ${sev.text}`}
            aria-hidden="true"
          >
            <Icon name={sev.icon} size={17} />
          </span>
          <div className="min-w-0 pt-0.5">
            <div className="flex flex-wrap items-center gap-2">
              <p className="truncate text-small font-semibold text-ink">{heading}</p>
              <Badge tone={sev.tone}>{sev.label}</Badge>
            </div>
          </div>
        </div>

        <div className="flex flex-none items-start gap-2 pt-0.5 text-right">
          <div>
            <p className="text-micro text-ink-faint">Opened {relativeTime(situation.first_seen_at)}</p>
            {situation.last_activity_at && (
              <p className={`mt-0.5 text-micro ${sev.text}`}>Last activity {relativeTime(situation.last_activity_at)}</p>
            )}
          </div>
          <Icon name="external" size={14} className="mt-0.5 flex-none text-ink-faint transition-colors group-hover:text-ink" />
        </div>
      </div>

      {(providers.length > 0 || situation.member_count > 0) && (
        <div className="flex items-center gap-2.5 pl-12 text-micro text-ink-faint">
          {providers.length > 0 && (
            <span className="flex items-center gap-1" aria-hidden="true">
              {providers.slice(0, MAX_GLYPHS).map((p) => {
                const Glyph = PROVIDER_GLYPH[p];
                return (
                  <span key={p} className="flex h-5 w-5 flex-none items-center justify-center rounded-sm">
                    {Glyph ? <Glyph /> : null}
                  </span>
                );
              })}
              {providers.length > MAX_GLYPHS && <span>+{providers.length - MAX_GLYPHS}</span>}
            </span>
          )}
          <span>
            {situation.member_count} finding{situation.member_count === 1 ? "" : "s"}
            {providers.length > 0 && ` · ${providers.length} service${providers.length === 1 ? "" : "s"}`}
          </span>
        </div>
      )}
    </Link>
  );
}
