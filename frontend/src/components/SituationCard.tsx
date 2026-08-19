import { Link } from "react-router-dom";

import type { SituationRow } from "../api/types";
import { PROVIDER_LABEL, severityOf } from "./situations";
import { Icon } from "./ui";

/**
 * A Situation, compressed to what distinguishes it from every other one.
 *
 * The old card printed the severity, the title, the member count and then the
 * full provider list as prose - and the page above it printed "Several things
 * about the same thing" as a subtitle, so the same idea was explained twice
 * before you reached the first real fact.
 *
 * A situation only needs to answer three things at a glance: how bad, what
 * it's about, and how much is behind it. The reasoning, evidence and
 * recommendations already have a page; this card's job is to get people there.
 */
export function SituationCard({ situation, compact = false }: { situation: SituationRow; compact?: boolean }) {
  const sev = severityOf(situation.severity);
  const providers = situation.providers.map((p) => PROVIDER_LABEL[p] ?? p);

  return (
    <Link
      to={`/situations/${situation.id}`}
      className={`group flex items-center gap-3 rounded-md border border-l-2 border-border bg-transparent px-4 py-3 transition-colors hover:border-border-strong hover:bg-surface/50 ${sev.stripe}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2.5">
          <span className={`flex-none text-micro font-medium ${sev.text}`}>{sev.label}</span>
          <p className="truncate text-small font-medium text-ink">{situation.entity ?? situation.title}</p>
        </div>
        <p className="mt-0.5 truncate text-micro text-ink-faint">
          {situation.member_count} finding{situation.member_count === 1 ? "" : "s"}
          {providers.length > 0 &&
            ` · ${compact ? `${providers.length} service${providers.length === 1 ? "" : "s"}` : providers.join(" · ")}`}
        </p>
      </div>
      <span className="flex-none text-ink-faint transition-colors group-hover:text-ink" aria-hidden="true">
        <Icon name="external" size={14} />
      </span>
    </Link>
  );
}
