import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Goal } from "../api/types";
import { dueLabel } from "../components/situations";
import { useWorkspace } from "../context/WorkspaceContext";
import {
  Badge,
  EmptyState,
  ItemList,
  ItemRow,
  PageHeader,
  SkeletonRows,
  type Tone,
} from "../components/ui";

/**
 * Goals, as the backend already assesses them.
 *
 * Like Memory, this was a link with no route behind it. It reads GET /goals and
 * shows the engine's own `health` and `health_reasons` - the assessment is not
 * recomputed here, and the reasons are shown verbatim behind the row's
 * disclosure because they are the checkable part.
 */
const HEALTH: Record<Goal["health"], { label: string; tone: Tone }> = {
  on_track: { label: "On track", tone: "good" },
  at_risk: { label: "At risk", tone: "warn" },
  blocked: { label: "Blocked", tone: "crit" },
  achieved: { label: "Achieved", tone: "good" },
  abandoned: { label: "Abandoned", tone: "neutral" },
  unknown: { label: "Not assessed", tone: "neutral" },
};

export function GoalsPage() {
  const { active } = useWorkspace();
  const [rows, setRows] = useState<Goal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Goal[]>("/goals")
      .then(setRows)
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Couldn't load goals");
        setRows([]);
      });
  }, [active?.id]);

  const open = (rows ?? []).filter((g) => !g.closed_at);
  const closed = (rows ?? []).filter((g) => g.closed_at);

  return (
    <div>
      <PageHeader
        title="Goals"
        description="What you're working towards, and how Sentinel currently reads each one."
      />

      {error && <p className="mb-4 text-caption text-crit">{error}</p>}

      {rows === null ? (
        <SkeletonRows rows={3} />
      ) : open.length === 0 ? (
        <EmptyState
          title="No goals yet."
          description="Goals give Sentinel something to measure activity against."
        />
      ) : (
        <ItemList>
          {open.map((g) => {
            const health = HEALTH[g.health] ?? HEALTH.unknown;
            return (
              <ItemRow
                key={g.id}
                tone={health.tone}
                icon="target"
                title={g.title}
                meta={[
                  g.outcome,
                  dueLabel(g.due_at),
                  g.progress !== null ? `${Math.round(g.progress * 100)}% complete` : null,
                ]}
                badge={<Badge tone={health.tone}>{health.label}</Badge>}
                // The engine's own reasons, verbatim - this is the checkable
                // part of the assessment, so it is shown rather than summarised.
                details={
                  g.health_reasons.length > 0 ? (
                    <ul className="flex flex-col gap-1">
                      {g.health_reasons.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  ) : (
                    (g.assessment ?? undefined)
                  )
                }
              />
            );
          })}
        </ItemList>
      )}

      {closed.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-2 text-micro font-semibold uppercase tracking-wide text-ink-faint">Closed</h2>
          <ItemList>
            {closed.map((g) => (
              <ItemRow
                key={g.id}
                tone="neutral"
                muted
                title={g.title}
                meta={[HEALTH[g.health]?.label ?? null]}
              />
            ))}
          </ItemList>
        </section>
      )}
    </div>
  );
}
