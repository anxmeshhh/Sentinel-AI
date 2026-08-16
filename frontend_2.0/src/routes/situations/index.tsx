import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { serviceByKey, severityColor, severityLabel } from "@/lib/sentinel-data";
import {
  Dot,
  EmptyState,
  InlineError,
  PageHeader,
  SkeletonRows,
} from "@/components/sentinel/primitives";
import { useSituations } from "@/lib/sentinel-live";

export const Route = createFileRoute("/situations/")({
  head: () => ({
    meta: [
      { title: "Situations · Sentinel" },
      {
        name: "description",
        content:
          "Related findings Sentinel connected to the same repository, channel or service.",
      },
      { property: "og:title", content: "Situations · Sentinel" },
      {
        property: "og:description",
        content: "Related findings connected to the same thing across your tools.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: SituationsPage,
});

const filters = ["All", "Critical", "Review", "Open", "Resolved"] as const;

function SituationsPage() {
  const [filter, setFilter] = useState<(typeof filters)[number]>("All");
  const { data, isLoading, isError, refetch } = useSituations();

  const rows = (data ?? []).filter((s) => {
    if (filter === "All") return true;
    if (filter === "Critical") return s.severity === "critical";
    if (filter === "Review") return s.severity === "review";
    if (filter === "Open") return s.status === "open";
    return s.status === "resolved";
  });

  return (
    <div>
      <PageHeader
        title="Situations"
        caption="Related findings Sentinel connected to the same thing."
      />

      <div className="mb-4 flex flex-wrap gap-1.5">
        {filters.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className="focus-ring t-caption rounded-[3px] px-2.5 py-1 transition-colors duration-150"
            style={
              filter === f
                ? { background: "var(--surface-2)", color: "var(--ink)" }
                : { color: "var(--ink-faint)" }
            }
          >
            {f}
          </button>
        ))}
      </div>

      {isError ? (
        <InlineError
          message="Sentinel couldn't load situations."
          onRetry={() => void refetch()}
        />
      ) : isLoading ? (
        <SkeletonRows rows={4} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No situations right now."
          body="A Situation forms when Sentinel finds two or more related things about the same repository, channel, or service."
        />
      ) : (
        <ul className="divide-y divide-border border-y border-border">
          {rows.map((s) => (
            <li key={s.id}>
              <Link
                to="/situations/$id"
                params={{ id: s.id }}
                className="flex w-full items-center gap-3 px-1 py-3 text-left transition-colors duration-150 hover:bg-surface/60"
              >
                <Dot color={severityColor[s.severity]} />
                <div className="min-w-0 flex-1">
                  <p className="t-small truncate text-ink">{s.entity}</p>
                  <p className="t-caption truncate text-ink-faint">
                    {s.findingIds.length} related findings ·{" "}
                    {s.providers.map((p) => serviceByKey(p)?.name).join(", ")}
                    {s.providers.length > 1 && " · across services"}
                  </p>
                </div>
                <span className="t-micro shrink-0 text-ink-faint">
                  {s.status === "resolved"
                    ? `Resolved ${s.resolvedAgo}`
                    : `${severityLabel[s.severity]} · ${s.lastActivity}`}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
