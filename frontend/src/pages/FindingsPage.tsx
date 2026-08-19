import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { AttentionItem } from "../api/types";
import { AttentionRows } from "../components/assistant/CommandCenter";
import { useWorkspace } from "../context/WorkspaceContext";
import { EmptyState, FilterChips, PageHeader, SkeletonRows } from "../components/ui";

/**
 * Findings - what Sentinel detected, as opposed to what you asked it to hold.
 *
 * There is no findings list endpoint; the backend exposes only
 * GET /findings/{id}. So this is not a new data source - it is GET /attention
 * filtered on `origin`, which is a real field the engines already set:
 * "detected" means Sentinel found it, "manual" means you wrote it down. That
 * distinction is the whole reason this page is not just a copy of /attention,
 * which shows both.
 *
 * If a real list endpoint appears later, only the fetch below changes.
 */
const FILTERS = [
  { key: "new", label: "Open" },
  { key: "done", label: "Resolved" },
  { key: "snoozed", label: "Snoozed" },
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

export function FindingsPage() {
  const { active } = useWorkspace();
  const [filter, setFilter] = useState<FilterKey>("new");
  const [items, setItems] = useState<AttentionItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setItems(null);
    api
      .get<AttentionItem[]>(`/attention?state=${filter}`)
      .then((rows) => setItems(rows.filter((i) => i.origin === "detected")))
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Couldn't load findings");
        setItems([]);
      });
  }, [filter, active?.id]);

  async function resolve(item: AttentionItem, state: "done" | "snoozed") {
    setItems((list) => (list ?? []).filter((i) => i.id !== item.id));
    const body =
      state === "snoozed"
        ? { state, snoozed_until: new Date(Date.now() + 24 * 3600 * 1000).toISOString() }
        : { state };
    try {
      await api.patch(`/attention/${item.id}`, body);
    } catch {
      setItems((list) => [item, ...(list ?? [])]);
    }
  }

  const sorted = [...(items ?? [])].sort((a, b) => b.priority - a.priority);

  return (
    <div>
      <PageHeader
        title="Findings"
        description="Everything Sentinel detected on its own, across your connected services."
      />

      <FilterChips className="mb-5" options={FILTERS} value={filter} onChange={setFilter} />

      {error && <p className="mb-4 text-caption text-crit">{error}</p>}

      {items === null ? (
        <SkeletonRows rows={5} />
      ) : sorted.length === 0 ? (
        <EmptyState
          title={filter === "new" ? "No open findings." : "Nothing here."}
          description="Findings appear when Sentinel detects something in a connected service."
        />
      ) : (
        <AttentionRows items={sorted} onResolve={resolve} />
      )}
    </div>
  );
}
