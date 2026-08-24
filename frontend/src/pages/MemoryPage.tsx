import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { MemoryRow } from "../api/types";
import { BackNav } from "../components/BackNav";
import { relativeTime, severityOf } from "../components/situations";
import { useWorkspace } from "../context/WorkspaceContext";
import {
  Action,
  ActionGroup,
  Badge,
  ButtonLink,
  EmptyState,
  ItemList,
  ItemRow,
  PageHeader,
  SkeletonRows,
  TabBar,
  type TabBarItem,
} from "../components/ui";

type TabKey = "active" | "forgotten";

/**
 * What Sentinel has learned - same shell as Attention, Situations and
 * Findings: a BackNav, a compact header, an underline TabBar for state
 * (Active/Forgotten) instead of two stacked sections.
 *
 * It reads the Memory Engine's own output through GET /memory and forgets
 * through POST /memory/{id}/forget; nothing here writes a memory, because
 * nothing in the product may. Severity comes from `evidence.severity` (the
 * recurring situation's own tier, via the same `severityOf` map Situations
 * and Attention already use) rather than a hardcoded "Insight" badge, and
 * `evidence.situation_id` links back to the situation the pattern was
 * learned from - both fields the API already returned, just not shown here.
 *
 * A memory forms deterministically, when a situation recurs. That is why the
 * empty state explains the mechanism rather than apologising: "none yet" is
 * the correct state for a workspace where nothing has happened twice.
 */
function evidenceOf(m: MemoryRow): { severity: string | null; situationId: string | null } {
  const e = m.evidence ?? {};
  const severity = typeof e.severity === "string" ? e.severity : null;
  const situationId = typeof e.situation_id === "string" ? e.situation_id : null;
  return { severity, situationId };
}

export function MemoryPage() {
  const { active } = useWorkspace();
  const [rows, setRows] = useState<MemoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("active");

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
  const visible = tab === "active" ? activeRows : forgotten;

  const tabs: TabBarItem<TabKey>[] = [
    { key: "active", label: "Active", count: activeRows.length },
    { key: "forgotten", label: "Forgotten", count: forgotten.length },
  ];

  return (
    <div>
      <BackNav back={{ to: "/", label: "Dashboard" }} />

      <PageHeader
        title="Memory"
        description="Patterns Sentinel has seen more than once. These raise the priority of anything that matches them."
      />

      <TabBar items={tabs} value={tab} onChange={setTab} />

      {error && <p className="mb-4 text-caption text-crit">{error}</p>}

      {rows === null ? (
        <SkeletonRows rows={4} />
      ) : visible.length === 0 ? (
        <EmptyState
          title={tab === "active" ? "Nothing remembered yet." : "Nothing forgotten."}
          description={
            tab === "active"
              ? "Memory forms on its own when the same situation happens more than once."
              : "Memories you forget stay listed here, never deleted outright."
          }
        />
      ) : (
        <ItemList>
          {visible.map((m) => {
            const { severity, situationId } = evidenceOf(m);
            const sev = severityOf(severity);
            return (
              <ItemRow
                key={m.id}
                tone={tab === "forgotten" ? "neutral" : sev.tone}
                muted={tab === "forgotten"}
                icon="brain"
                title={m.summary}
                meta={[
                  `Seen ${m.observation_count} time${m.observation_count === 1 ? "" : "s"}`,
                  m.last_observed_at ? `last ${relativeTime(m.last_observed_at)}` : null,
                ]}
                badge={tab === "active" ? <Badge tone={sev.tone}>{sev.label}</Badge> : undefined}
                actions={
                  <ActionGroup>
                    {situationId && (
                      <ButtonLink to={`/situations/${situationId}`} variant="ghost" size="sm">
                        View Situation
                      </ButtonLink>
                    )}
                    {tab === "active" && (
                      <Action
                        kind="dismiss"
                        label="Forget"
                        loading={busy === m.id}
                        onClick={() => void forget(m.id)}
                      />
                    )}
                  </ActionGroup>
                }
              />
            );
          })}
        </ItemList>
      )}
    </div>
  );
}
