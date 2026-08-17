import { useEffect, useRef, useState } from "react";

import { ActionPanel } from "./ActionPanel";
import { CommitmentStrip } from "./CommitmentStrip";
import { GoalPanel } from "./GoalPanel";
import { ProactiveStrip } from "./ProactiveStrip";

export type TabKey = "now" | "risks" | "commitments" | "goals";

const TABS: { key: TabKey; label: string; question: string }[] = [
  { key: "now", label: "Now", question: "What needs my attention, and what does Sentinel want to do?" },
  { key: "risks", label: "Risks", question: "What is developing that nobody asked about?" },
  { key: "commitments", label: "Commitments", question: "What was promised, and is it slipping?" },
  { key: "goals", label: "Goals", question: "Are the outcomes we want actually going to happen?" },
];

/**
 * One question at a time.
 *
 * These four surfaces were originally stacked down a single page, which put
 * five panels in competition for the top of one screen and buried the
 * attention list - the thing a person opens this page for. Each answers a
 * genuinely different question, so each gets its own tab, and the tab bar
 * states the question rather than just naming the feature.
 *
 * "Now" deliberately holds two things: what arrived that needs a decision,
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
  counts,
  autoFocus,
}: {
  scope: "personal" | "channel";
  teamId?: string;
  /** The attention list itself, rendered by the page that owns its state. */
  attention: React.ReactNode;
  counts?: { attention?: number; risks?: number; commitments?: number; goals?: number };
  /** The tab to open by default so the content matches the verdict - the
   *  highest-priority non-empty category. Applied once, when it first
   *  arrives; a manual tab click from then on always wins. */
  autoFocus?: TabKey;
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
    };
    const value = map[key];
    return value && value > 0 ? value : undefined;
  }

  return (
    <div>
      <div
        role="tablist"
        aria-label="Sentinel intelligence"
        className="mb-2 flex flex-wrap gap-1 border-b border-border"
      >
        {TABS.map((t) => {
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


      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "now" && (
          <>
            {/* Findings first. The action composer used to sit above them, so
                the page opened with an empty text box and its explanation, and
                the things needing attention began ~900px down. A tool belongs
                after the content it acts on. */}
            {attention}
            <ActionPanel scope={scope} teamId={teamId} />
          </>
        )}
        {tab === "risks" && <ProactiveStrip scope={scope} teamId={teamId} alwaysShow />}
        {tab === "commitments" && <CommitmentStrip scope={scope} teamId={teamId} />}
        {tab === "goals" && <GoalPanel scope={scope} teamId={teamId} />}
      </div>
    </div>
  );
}
