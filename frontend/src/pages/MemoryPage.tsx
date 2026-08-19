import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { MemoryRow } from "../api/types";
import { relativeTime } from "../components/situations";
import { useWorkspace } from "../context/WorkspaceContext";
import { Action, ActionGroup, Badge, EmptyState, ItemList, ItemRow, PageHeader, SkeletonRows } from "../components/ui";

/**
 * What Sentinel has learned.
 *
 * This page existed only as a destination other screens linked to - "View
 * memory" and the dashboard rail both pointed at /memory, which had no route
 * and 404'd. It reads the Memory Engine's own output through GET /memory and
 * forgets through POST /memory/{id}/forget; nothing here writes a memory,
 * because nothing in the product may.
 *
 * A memory forms deterministically, when a situation recurs. That is why the
 * empty state explains the mechanism rather than apologising: "none yet" is
 * the correct state for a workspace where nothing has happened twice.
 */
export function MemoryPage() {
  const { active } = useWorkspace();
  const [rows, setRows] = useState<MemoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try {
      setRows(await api.get<MemoryRow[]>("/memory"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load memory");
      setRows([]);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id]);

  async function forget(id: string) {
    setBusy(id);
    try {
      await api.post(`/memory/${id}/forget`);
      setRows((list) => (list ?? []).map((m) => (m.id === id ? { ...m, status: "forgotten" } : m)));
    } finally {
      setBusy(null);
    }
  }

  const activeRows = (rows ?? []).filter((m) => m.status === "active");
  const forgotten = (rows ?? []).filter((m) => m.status === "forgotten");

  return (
    <div>
      <PageHeader
        title="Memory"
        description="Patterns Sentinel has seen more than once. These raise the priority of anything that matches them."
      />

      {error && <p className="mb-4 text-caption text-crit">{error}</p>}

      {rows === null ? (
        <SkeletonRows rows={4} />
      ) : activeRows.length === 0 ? (
        <EmptyState
          title="Nothing remembered yet."
          description="Memory forms on its own when the same situation happens more than once."
        />
      ) : (
        <ItemList>
          {activeRows.map((m) => (
            <ItemRow
              key={m.id}
              tone="good"
              icon="brain"
              title={m.summary}
              meta={[
                `Seen ${m.observation_count} time${m.observation_count === 1 ? "" : "s"}`,
                m.last_observed_at ? `last ${relativeTime(m.last_observed_at)}` : null,
              ]}
              badge={<Badge tone="good">Insight</Badge>}
              actions={
                <ActionGroup>
                  <Action
                    kind="dismiss"
                    label="Forget"
                    loading={busy === m.id}
                    onClick={() => void forget(m.id)}
                  />
                </ActionGroup>
              }
            />
          ))}
        </ItemList>
      )}

      {forgotten.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-2 text-micro font-semibold uppercase tracking-wide text-ink-faint">
            Forgotten
          </h2>
          <ItemList>
            {forgotten.map((m) => (
              <ItemRow key={m.id} tone="neutral" muted title={m.summary} meta={["No longer applied"]} />
            ))}
          </ItemList>
        </section>
      )}
    </div>
  );
}
