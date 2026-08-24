import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { AttentionItem } from "../api/types";
import { AttentionRows } from "../components/assistant/CommandCenter";
import { BackNav } from "../components/BackNav";
import { priorityOf } from "../components/situations";
import { useWorkspace } from "../context/WorkspaceContext";
import { EmptyState, PageHeader, SeverityFilter, SkeletonRows } from "../components/ui";

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
 * Same shell as Attention and Situations: an underline tab bar for state with
 * a compact filter at its right edge, and rows that are the exact same
 * ItemRow/AttentionRows the Command Center and Attention already render - a
 * finding looks like a finding everywhere it appears.
 *
 * If a real list endpoint appears later, only the fetch below changes.
 */
const FILTERS = [
  { key: "new", label: "Open" },
  { key: "done", label: "Resolved" },
  { key: "snoozed", label: "Snoozed" },
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

/** In ladder order, matching the four-step priority scale `priorityOf`
 *  derives from the engine's own priority float - nothing invented here. */
const SEVERITY_FILTERS = ["Critical", "High", "Medium", "Low"] as const;

export function FindingsPage() {
  const { active } = useWorkspace();
  const [filter, setFilter] = useState<FilterKey>("new");
  const [severity, setSeverity] = useState<string | null>(null);
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
  const visible = severity ? sorted.filter((i) => priorityOf(i).label === severity) : sorted;

  return (
    <div>
      <BackNav back={{ to: "/", label: "Dashboard" }} />

      <PageHeader
        title="Findings"
        description="Everything Sentinel detected on its own, across your connected services."
      />

      <div className="mb-5 flex flex-wrap items-center justify-between gap-2 border-b border-border">
        <div role="tablist" aria-label="Finding status" className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              role="tab"
              aria-selected={filter === f.key}
              onClick={() => setFilter(f.key)}
              className={`-mb-px border-b-2 px-3 py-2 text-small transition-colors ${
                filter === f.key
                  ? "border-accent font-semibold text-ink"
                  : "border-transparent text-ink-faint hover:text-ink-dim"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="pb-1.5">
          <SeverityFilter
            value={severity}
            options={SEVERITY_FILTERS.map((s) => ({ value: s, label: s }))}
            onChange={setSeverity}
          />
        </div>
      </div>

      {error && <p className="mb-4 text-caption text-crit">{error}</p>}

      {items === null ? (
        <SkeletonRows rows={5} />
      ) : visible.length === 0 ? (
        <EmptyState
          title={
            sorted.length > 0
              ? "Nothing matches that filter."
              : filter === "new"
                ? "No open findings."
                : "Nothing here."
          }
          description={
            sorted.length > 0
              ? "Try a different severity, or clear the filter."
              : "Findings appear when Sentinel detects something in a connected service."
          }
        />
      ) : (
        <AttentionRows items={visible} onResolve={resolve} />
      )}
    </div>
  );
}
