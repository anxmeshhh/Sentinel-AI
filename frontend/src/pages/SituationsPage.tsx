import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { SituationRow } from "../api/types";
import { BackNav } from "../components/BackNav";
import { EmptyState, PageHeader, SkeletonRows } from "../components/ui";
import { PROVIDER_LABEL, relativeTime, severityOf } from "../components/situations";

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

      <div className="mb-5 flex flex-wrap gap-1.5">
        {(["open", "resolved", "all"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-md px-2.5 py-1 text-caption capitalize transition-colors ${
              filter === f ? "bg-surface-2 text-ink" : "text-ink-faint hover:text-ink"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {error ? (
        <p className="text-caption text-crit">{error}</p>
      ) : rows === null ? (
        <SkeletonRows rows={4} />
      ) : rows.length === 0 ? (
        <EmptyState
          title={filter === "resolved" ? "Nothing has been resolved yet." : "No situations right now."}
          description="A situation forms when Sentinel finds two or more related things about the same repository, channel or service — a repo that went quiet, a meeting about it, and an overdue task, for instance."
        />
      ) : (
        <ul className="divide-y divide-border border-y border-border">
          {rows.map((s) => {
            const sev = severityOf(s.severity);
            return (
              <li key={s.id}>
                <Link
                  to={`/situations/${s.id}`}
                  className="flex items-start gap-3 px-1 py-3.5 transition-colors hover:bg-surface/60"
                >
                  <span
                    aria-hidden="true"
                    className={`mt-[7px] h-1.5 w-1.5 flex-none rounded-full ${sev.dot}`}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-small text-ink">
                      {s.entity ?? s.title}
                    </span>
                    <span className="block truncate text-caption text-ink-faint">
                      {s.member_count} related findings
                      {s.providers.length > 0 &&
                        ` · ${s.providers.map((p) => PROVIDER_LABEL[p] ?? p).join(", ")}`}
                      {s.occurrence_count > 1 && ` · seen ${s.occurrence_count} times`}
                    </span>
                  </span>
                  <span className="flex-none text-right text-micro text-ink-faint">
                    <span className={`block ${s.status === "resolved" ? "text-good" : sev.text}`}>
                      {s.status === "resolved" ? "Resolved" : sev.label}
                    </span>
                    <span className="block">
                      {relativeTime(s.status === "resolved" ? s.resolved_at : s.last_activity_at)}
                    </span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
