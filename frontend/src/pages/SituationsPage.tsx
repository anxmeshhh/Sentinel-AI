import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { SituationRow } from "../api/types";
import { SituationsRail } from "../components/assistant/CommandCenter";
import { BackNav } from "../components/BackNav";
import { SEVERITY } from "../components/situations";
import { SituationCard } from "../components/SituationCard";
import { EmptyState, PageHeader, SeverityFilter, SkeletonRows } from "../components/ui";
import { useIntelligence } from "../hooks/useIntelligence";

const STATUS_TABS = [
  { key: "open", label: "Open" },
  { key: "resolved", label: "Resolved" },
  { key: "all", label: "All" },
] as const;

type StatusFilter = (typeof STATUS_TABS)[number]["key"];

/** Severity as a filter, in ladder order - not object key order, which would
 *  put Reminder before Review. */
const SEVERITY_FILTERS = ["critical", "review", "reminder"] as const;

/**
 * Situations - the Intelligence Core's most synthesised output.
 *
 * A Situation is two or more findings that concern the SAME real-world thing.
 * That is the whole product thesis, so the empty state teaches it rather than
 * apologising: someone who has never seen one should still learn what would
 * make one appear.
 *
 * Same visual language as Attention: an underline tab bar with a compact
 * filter at its right edge, spacious cards over a dense list, and a rail
 * that only ever shows sections it has real data for.
 */
export function SituationsPage() {
  const [rows, setRows] = useState<SituationRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusFilter>("open");
  const [severity, setSeverity] = useState<string | null>(null);

  // The rail's "What this concerns" / "Services involved" / Memory / Watching
  // come from the shared Core hook, same as Attention - the top open
  // situation here can never disagree with the one Attention or the
  // Dashboard names as current.
  const intel = useIntelligence();

  useEffect(() => {
    setRows(null);
    setError(null);
    api
      .get<SituationRow[]>(`/situations${status === "all" ? "" : `?status=${status}`}`)
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load situations"));
  }, [status]);

  const visible = useMemo(
    () => (severity ? (rows ?? []).filter((s) => (s.severity ?? "review") === severity) : rows),
    [rows, severity],
  );

  return (
    <div className="flex gap-6">
      <div className="flex min-w-0 flex-1 flex-col">
        <BackNav
          back={{ to: "/", label: "Dashboard" }}
          crumbs={[{ label: "Dashboard", to: "/" }, { label: "Situations" }]}
        />

        <PageHeader
          title="Situations"
          description="When several things across your tools turn out to be about the same repository, channel or service, Sentinel groups them here."
        />

        <div className="mb-5 flex flex-wrap items-center justify-between gap-2 border-b border-border">
          <div role="tablist" aria-label="Situation status" className="flex gap-1">
            {STATUS_TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={status === t.key}
                onClick={() => setStatus(t.key)}
                className={`-mb-px border-b-2 px-3 py-2 text-small transition-colors ${
                  status === t.key
                    ? "border-accent font-semibold text-ink"
                    : "border-transparent text-ink-faint hover:text-ink-dim"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="pb-1.5">
            <SeverityFilter
              value={severity}
              options={SEVERITY_FILTERS.map((s) => ({ value: s, label: SEVERITY[s]!.label }))}
              onChange={setSeverity}
            />
          </div>
        </div>

        {error ? (
          <p className="text-caption text-crit">{error}</p>
        ) : visible === null ? (
          <SkeletonRows rows={4} />
        ) : visible.length === 0 ? (
          <EmptyState
            title={
              rows && rows.length > 0
                ? "Nothing matches that filter."
                : status === "resolved"
                  ? "Nothing has been resolved yet."
                  : "No situations right now."
            }
            description={
              rows && rows.length > 0
                ? "Try a different severity, or clear the filter."
                : "Situations form when two or more findings point at the same repository, channel or service."
            }
          />
        ) : (
          <ul className="flex flex-col gap-2.5">
            {visible.map((s) => (
              <li key={s.id}>
                <SituationCard situation={s} />
              </li>
            ))}
          </ul>
        )}
      </div>

      <SituationsRail intel={intel} />
    </div>
  );
}
