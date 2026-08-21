import { useEffect, useRef, useState, type ReactNode } from "react";

import { ActionPanel } from "./ActionPanel";
import { CommitmentStrip } from "./CommitmentStrip";
import { GoalPanel } from "./GoalPanel";
import { ProactiveStrip } from "./ProactiveStrip";

export type TabKey = "now" | "risks" | "commitments" | "goals" | "insights";

const TABS: { key: TabKey; label: string; question: string }[] = [
  { key: "now", label: "All", question: "What needs my attention, and what does Sentinel want to do?" },
  { key: "risks", label: "Risks", question: "What is developing that nobody asked about?" },
  { key: "commitments", label: "Commitments", question: "What was promised, and is it slipping?" },
  { key: "goals", label: "Goals", question: "Are the outcomes we want actually going to happen?" },
  { key: "insights", label: "Insights", question: "What has Sentinel learned that's worth knowing?" },
];

/**
 * One question at a time.
 *
 * These surfaces were originally stacked down a single page, which put five
 * panels in competition for the top of one screen and buried the attention
 * list - the thing a person opens this page for. Each answers a genuinely
 * different question, so each gets its own tab, and the tab bar states the
 * question rather than just naming the feature.
 *
 * "All" deliberately holds two things: what arrived that needs a decision,
 * and what Sentinel is asking permission to do. Both are "something is
 * waiting on you", and splitting them would mean checking two places to
 * learn whether anything is.
 *
 * Badges are the counts that matter - things awaiting a decision - so a
 * quiet tab looks quiet.
 */
export function IntelligenceTabs({
  scope,
  teamId,
  attention,
  insights,
  counts,
  autoFocus,
  compact = false,
  filterSlot,
}: {
  scope: "personal" | "channel";
  teamId?: string;
  /** The attention list itself, rendered by the page that owns its state. */
  attention: React.ReactNode;
  /** Insights tab content (Memory), rendered by the page that owns that
   *  data - same pattern as `attention`, so this component stays
   *  data-agnostic. A channel caller that omits it gets a plain fallback. */
  insights?: ReactNode;
  counts?: { attention?: number; risks?: number; commitments?: number; goals?: number; insights?: number };
  /** The tab to open by default so the content matches the verdict - the
   *  highest-priority non-empty category. Applied once, when it first
   *  arrives; a manual tab click from then on always wins. */
  autoFocus?: TabKey;
  /** Forwarded to ActionPanel: hides the free-text composer, catalogue and
   *  executed-actions history, which the caller is rendering elsewhere (the
   *  Assistant, and its own Recent Activity section). Only the Attention
   *  page passes this; channel usage is unaffected. */
  compact?: boolean;
  /** An extension point at the right end of the tab row - the Attention
   *  page's state filter (Open/Snoozed/Done/Dismissed) lives here rather
   *  than being hardcoded, since the other tabs have no such filter. */
  filterSlot?: ReactNode;
}) {
  const [tab, setTab] = useState<TabKey>("now");
  // The page decides the opening tab from data that loads asynchronously, so
  // autoFocus arrives after mount. Apply it the moment it does - but never
  // over a tab the user has already chosen themselves.
  const touched = useRef(false);
  useEffect(() => {
    if (autoFocus && !touched.current) setTab(autoFocus);
  }, [autoFocus]);
  function selectTab(key: TabKey) {
    touched.current = true;
    setTab(key);
  }

  function badge(key: TabKey): number | undefined {
    const map: Record<TabKey, number | undefined> = {
      now: counts?.attention,
      risks: counts?.risks,
      commitments: counts?.commitments,
      goals: counts?.goals,
      insights: counts?.insights,
    };
    const value = map[key];
    return value && value > 0 ? value : undefined;
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 border-b border-border">
        <div role="tablist" aria-label="Sentinel intelligence" className="flex flex-wrap gap-1">
          {/* Insights only appears for a caller that actually supplies content
           *  for it - channel usage doesn't pass `insights` at all, and gets
           *  the same four tabs it always has, unchanged. */}
          {TABS.filter((t) => t.key !== "insights" || insights !== undefined).map((t) => {
            const selected = tab === t.key;
            const count = badge(t.key);
            return (
              <button
                key={t.key}
                role="tab"
                aria-selected={selected}
                aria-controls={`panel-${t.key}`}
                id={`tab-${t.key}`}
                onClick={() => selectTab(t.key)}
                className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-small transition-colors ${
                  selected
                    ? "border-accent font-semibold text-ink"
                    : "border-transparent text-ink-faint hover:text-ink-dim"
                }`}
              >
                {t.label}
                {count !== undefined && (
                  <span className="rounded-full bg-surface-2 px-1.5 py-px font-mono text-micro text-ink-dim">
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {filterSlot && <div className="pb-1.5">{filterSlot}</div>}
      </div>

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "now" && (
          <>
            {/* Findings first. The action composer used to sit above them, so
                the page opened with an empty text box and its explanation, and
                the things needing attention began ~900px down. A tool belongs
                after the content it acts on. */}
            {attention}
            <ActionPanel scope={scope} teamId={teamId} compact={compact} />
          </>
        )}
        {tab === "risks" && <ProactiveStrip scope={scope} teamId={teamId} alwaysShow />}
        {tab === "commitments" && <CommitmentStrip scope={scope} teamId={teamId} />}
        {tab === "goals" && <GoalPanel scope={scope} teamId={teamId} />}
        {tab === "insights" &&
          (insights ?? <p className="text-caption text-ink-faint">Nothing learned yet.</p>)}
      </div>
    </div>
  );
}
