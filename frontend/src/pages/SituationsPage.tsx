import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { SituationRow } from "../api/types";
import { BackNav } from "../components/BackNav";
import { EmptyState, FilterChips, PageHeader, SkeletonRows } from "../components/ui";
import { SituationCard } from "../components/SituationCard";

/**
 * Situations - the Intelligence Core's most synthesised output, and until now
 * the one thing with no page of its own.
 *
 * A Situation is two or more findings that concern the SAME real-world thing.
 * That is the whole product thesis, so the empty state teaches it rather than
 * apologising: someone who has never seen one should still learn what would
 * make one appear.
 */
export function SituationsPage() {
  const [rows, setRows] = useState<SituationRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "open" | "resolved">("open");

  useEffect(() => {
    setRows(null);
    setError(null);
    api
      .get<SituationRow[]>(`/situations${filter === "all" ? "" : `?status=${filter}`}`)
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load situations"));
  }, [filter]);

  return (
    <div>
      <BackNav back={{ to: "/", label: "Dashboard" }} crumbs={[{ label: "Dashboard", to: "/" }, { label: "Situations" }]} />

      <PageHeader
        title="Situations"
        description="When several things across your tools turn out to be about the same repository, channel or service, Sentinel groups them here."
      />

      <FilterChips
        className="mb-5"
        options={[
          { key: "open", label: "Open" },
          { key: "resolved", label: "Resolved" },
          { key: "all", label: "All" },
        ] as const}
        value={filter}
        onChange={setFilter}
      />

      {error ? (
        <p className="text-caption text-crit">{error}</p>
      ) : rows === null ? (
        <SkeletonRows rows={4} />
      ) : rows.length === 0 ? (
        <EmptyState
          title={filter === "resolved" ? "Nothing has been resolved yet." : "No situations right now."}
          description="Situations form when two or more findings point at the same repository, channel or service."
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((s) => (
            <li key={s.id}>
              <SituationCard situation={s} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
