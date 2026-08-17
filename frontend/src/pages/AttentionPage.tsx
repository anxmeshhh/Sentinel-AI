import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import { api, ApiError } from "../api/client";
import type { AttentionItem, CalendarPlan, Commitment, Goal, SentinelStatus, Situation } from "../api/types";
import { EvidenceLink } from "../components/AttentionStrip";
import { BackNav } from "../components/BackNav";
import { SentinelPanel } from "../components/SentinelPanel";
import { workspaceContext } from "../components/context";
import { useWorkspace } from "../context/WorkspaceContext";
import { MeetingBriefPanel, useMeetingBrief } from "../components/MeetingBriefPanel";
import { InvestigationPanel, useInvestigation } from "../components/InvestigationPanel";
import { IntelligenceTabs, type TabKey } from "../components/IntelligenceTabs";
import {
  FindingsEmptyState,
  ProvidersChecked,
  SentinelStatusCard,
} from "../components/SentinelStatusPanel";
import { LoadingBlock, Overflow, OverflowItem } from "../components/ui";
import { PROVIDER_LABEL } from "../components/situations";

const STATE_FILTERS = [
  { key: "new", label: "Open" },
  { key: "snoozed", label: "Snoozed" },
  { key: "done", label: "Done" },
  { key: "dismissed", label: "Dismissed" },
];

const SNOOZE_OPTIONS = [
  { label: "3 hours", hours: 3 },
  { label: "Tomorrow", hours: 24 },
  { label: "Next week", hours: 24 * 7 },
];

/** Provider names come from the shared map, not a local copy.
 *
 *  The copy that lived here knew about five providers and had not been touched
 *  since - so Outlook, To Do, OneDrive, OneNote, Teams and Zoom all fell
 *  through to their raw ids and rendered as "microsoft_outlook_calendar" on a
 *  user-facing card. One map, or this happens again with the next provider. */
function providerLabel(src: string | null): string | null {
  if (!src) return null;
  if (src === "agent") return "Sentinel";
  return PROVIDER_LABEL[src] ?? src;
}

/** SECTION 8: the finding's severity, read straight from its priority so the
 *  card leads with "how serious" before anything else. Manual reminders are
 *  never "critical" - they are the user's own notes. */
function severityOf(item: AttentionItem): { dot: string; label: string } {
  if (item.origin === "manual") return { dot: "bg-watch", label: "Reminder" };
  if (item.priority >= 0.8) return { dot: "bg-crit", label: "Critical" };
  if (item.priority >= 0.5) return { dot: "bg-warn", label: "Needs review" };
  return { dot: "bg-watch", label: "FYI" };
}

/** SECTION 8: the recommended action, deterministic and free on every card -
 *  a template keyed to the finding's type. It answers "what do I do" without
 *  an LLM call; Investigate deepens it into specifics. Manual reminders are
 *  the user's own notes and carry no recommendation. */
const RECOMMENDED: Record<string, string> = {
  important_email: "Reply, or archive if it's handled",
  upcoming_meeting: "Prepare before it starts",
  stale_pr: "Review it, or nudge the author",
  deadline: "Act before it's due",
  finding: "Review the details, then decide",
  conversation_mention: "Reply in the thread, or delegate it",
  conversation_blocker: "Unblock it, or escalate the blocker",
  conversation_urgent: "Open the channel and triage",
};

function recommendedAction(item: AttentionItem): string | null {
  return item.origin === "manual" ? null : RECOMMENDED[item.type] ?? "Review and decide";
}

/** A due date said the way a person says it. `toLocaleString()` produced
 *  "18/08/2026, 00:04:54", which reads as a log entry rather than a deadline. */
function dueLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (sameDay) return `today ${time}`;
  return `${d.toLocaleDateString([], { day: "numeric", month: "short" })}, ${time}`;
}

/** The tab the page should open on, so the content immediately matches the
 *  narrative verdict: the highest-priority non-empty category. Critical items
 *  live in Now (a critical attention item) or Risks (a critical situation) -
 *  open where they actually are. Below critical, the order is the intended
 *  Risks -> Commitments -> Goals -> Now, with Now as the quiet default. */
function pickFocusTab(
  status: SentinelStatus,
  counts: { risks?: number; commitments?: number; goals?: number },
  open: AttentionItem[],
): TabKey {
  const criticalAttention = open.filter((i) => i.origin === "detected" && i.priority >= 0.8).length;
  if (status.critical_count > 0) return criticalAttention > 0 ? "now" : "risks";
  if ((counts.risks ?? 0) > 0) return "risks";
  if ((counts.commitments ?? 0) > 0) return "commitments";
  if ((counts.goals ?? 0) > 0) return "goals";
  return "now";
}

function shortTime(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function AttentionPage() {
  const { active } = useWorkspace();
  const [stateFilter, setStateFilter] = useState("new");
  const [items, setItems] = useState<AttentionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [askItem, setAskItem] = useState<AttentionItem | null>(null);
  const [addingReminder, setAddingReminder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<{ item: AttentionItem; plan: CalendarPlan } | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [planResult, setPlanResult] = useState<string | null>(null);
  const [prepItemId, setPrepItemId] = useState<string | null>(null);
  const meetingBrief = useMeetingBrief();
  const [investigateItemId, setInvestigateItemId] = useState<string | null>(null);
  const investigation = useInvestigation();

  // Page-level "is Sentinel working, and how much needs me" state, kept
  // separate from the visible filter list so the status card and summary
  // always reflect the open picture regardless of which filter is shown.
  const [status, setStatus] = useState<SentinelStatus | null>(null);
  const [openItems, setOpenItems] = useState<AttentionItem[]>([]);
  const [tabCounts, setTabCounts] = useState<{ risks?: number; commitments?: number; goals?: number }>({});
  const [focusTab, setFocusTab] = useState<TabKey | undefined>(undefined);
  const [assistantOpen, setAssistantOpen] = useState(false);

  const [newTitle, setNewTitle] = useState("");
  const [newDue, setNewDue] = useState("");

  async function load(filter = stateFilter) {
    setLoading(true);
    try {
      setItems(await api.get<AttentionItem[]>(`/attention?state=${filter}`));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  /** Everything the status card, summary, tab badges and opening tab need. All
   *  non-fatal: the findings list stands on its own if any of these fail. */
  async function loadMeta() {
    // The dismissed list is no longer fetched: it existed only to count a
    // number for the "Today" row, which is gone. One request less per load.
    const [st, open, r, c, g] = await Promise.all([
      api.get<SentinelStatus>("/attention/status").catch(() => null),
      api.get<AttentionItem[]>("/attention?state=new").catch(() => [] as AttentionItem[]),
      api.get<Situation[]>("/proactive").catch(() => null),
      api.get<Commitment[]>("/commitments").catch(() => null),
      api.get<Goal[]>("/goals").catch(() => null),
    ]);
    setStatus(st);
    setOpenItems(open);
    const counts = { risks: r?.length, commitments: c?.length, goals: g?.length };
    setTabCounts(counts);
    // Decide the opening tab once, when the counts are in. IntelligenceTabs
    // applies it only until the user picks a tab themselves.
    if (st) setFocusTab(pickFocusTab(st, counts, open));
  }

  useEffect(() => {
    void load(stateFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stateFilter]);

  useEffect(() => {
    void loadMeta();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // SECTION 5: the assistant stays collapsed by default - a quiet "Need help?"
  // below the findings - so it supports Sentinel's intelligence rather than
  // competing with it for the eye. The user opens it when they want it; it
  // never fronts the primary content.
  const findingsCount = status?.findings_count ?? 0;

  function investigateFor(item: AttentionItem) {
    if (investigateItemId === item.id) {
      setInvestigateItemId(null);
      investigation.clear();
      return;
    }
    setInvestigateItemId(item.id);
    void investigation.load(`/attention/${item.id}/investigate`);
  }

  async function setState(item: AttentionItem, state: string, snoozeHours?: number) {
    setItems((list) => list.filter((i) => i.id !== item.id));
    try {
      await api.patch(`/attention/${item.id}`, {
        state,
        ...(snoozeHours ? { snoozed_until: new Date(Date.now() + snoozeHours * 3600 * 1000).toISOString() } : {}),
      });
      void loadMeta();
    } catch {
      setItems((list) => [item, ...list]);
    }
  }

  async function refresh() {
    setRefreshing(true);
    try {
      await api.post<AttentionItem[]>("/attention/refresh");
      await load();
      await loadMeta();
    } finally {
      setRefreshing(false);
    }
  }

  async function prepareFor(item: AttentionItem) {
    setPrepItemId(item.id);
    meetingBrief.clear();
    await meetingBrief.load(`/attention/${item.id}/prepare`);
  }

  async function proposeCalendar(item: AttentionItem) {
    setPlanResult(null);
    try {
      const proposed = await api.post<CalendarPlan>(`/attention/${item.id}/calendar-plan`);
      setPlan({ item, plan: proposed });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't build a calendar plan for this.");
    }
  }

  async function confirmCalendar() {
    if (!plan) return;
    setPlanBusy(true);
    try {
      await api.post("/connections/google/command/execute", {
        name: "create_calendar_event",
        arguments: { title: plan.plan.title, start: plan.plan.start, end: plan.plan.end },
      });
      setPlanResult("Added to your calendar.");
      setPlan(null);
    } catch (e) {
      setPlanResult(e instanceof ApiError ? e.message : "Couldn't add it to your calendar.");
    } finally {
      setPlanBusy(false);
    }
  }

  async function addReminder(e: FormEvent) {
    e.preventDefault();
    if (!newTitle.trim()) return;
    await api.post("/attention", {
      title: newTitle.trim(),
      due_at: newDue ? new Date(newDue).toISOString() : null,
    });
    setNewTitle("");
    setNewDue("");
    if (stateFilter === "new") await load();
    void loadMeta();
  }

  // The Now tab holds attention items only - situations live in Risks - so its
  // badge counts attention items, while the verdict and Today's summary count
  // the full operational state (attention + situations) from the backend.
  const nowCount = openItems.filter((i) => i.origin === "detected").length;

  // SECTION 3: the all-clear only reassures if the sync genuinely ran. Show it
  // only for the open filter with nothing detected; other filters get a plain
  // "nothing here" so an empty Done tab doesn't read as an all-clear.
  const showAllClear = stateFilter === "new" && status !== null && findingsCount === 0;

  const findingsList =
    loading ? (
      <LoadingBlock />
    ) : items.length === 0 ? (
      showAllClear ? (
        <FindingsEmptyState status={status} />
      ) : (
        <p className="rounded-md border border-border px-4 py-6 text-center text-small text-ink-faint">
          Nothing in {STATE_FILTERS.find((f) => f.key === stateFilter)?.label.toLowerCase()}.
        </p>
      )
    ) : (
      <div className="flex flex-col gap-2">
        {items.map((item) => {
          const sev = severityOf(item);
          const src = providerLabel(item.source_provider);
          return (
            <div
              key={item.id}
              className={`rounded-md border bg-surface p-3.5 ${askItem?.id === item.id ? "border-border-strong" : "border-border"}`}
            >
              <div className="flex items-start gap-3">
                <span aria-hidden className={`mt-1.5 inline-block h-2 w-2 flex-none rounded-full ${sev.dot}`} title={sev.label} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-3">
                    <div className={`text-body font-semibold ${item.state === "done" ? "text-ink-faint line-through" : "text-ink"}`}>
                      {item.title}
                    </div>
                    <div className="flex flex-none items-center gap-2 pt-0.5 text-micro text-ink-faint">
                      {src && <span>{src}</span>}
                      <span aria-hidden>·</span>
                      <span title={new Date(item.created_at).toLocaleString()}>{shortTime(item.created_at)}</span>
                    </div>
                  </div>
                  {/* SECTION 8: why Sentinel surfaced this - a fact, labelled as one. */}
                  {/* Why Sentinel surfaced this. Deliberately just the fact:
                      "detected" and a confidence label were decoration on a
                      line that already carries the reason, and a raw
                      toLocaleString due date read as a log entry. */}
                  <div className="mt-1 text-caption text-ink-dim">
                    {item.why}
                    {item.due_at && ` · due ${dueLabel(item.due_at)}`}
                    {item.state === "snoozed" && item.snoozed_until && ` · snoozed until ${dueLabel(item.snoozed_until)}`}
                  </div>
                  {/* SECTION 8: what to do + how sure - deterministic, on the card. */}
                  {item.state === "new" && recommendedAction(item) && (
                    <div className="mt-1.5 text-caption">
                      <span className="text-ink-faint">▸ Recommended </span>
                      <span className="text-ink">{recommendedAction(item)}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Two actions, and a menu.
                  This row used to print seven links side by side - Mark done,
                  Snooze, Dismiss, Prepare Me, Investigate, Ask Sentinel, Open -
                  which is a menu laid out flat, with nothing reading as
                  primary. What people actually do is finish it or go look at
                  it; everything else is one click away. */}
              <div className="mt-2.5 flex flex-wrap items-center gap-3 pl-5 text-caption">
                {item.state === "new" ? (
                  <>
                    <button
                      onClick={() => setState(item, "done")}
                      className="text-ink-faint underline underline-offset-2 hover:text-good"
                    >
                      Done
                    </button>
                    <Overflow align="left">
                      {(close) => (
                        <>
                          {SNOOZE_OPTIONS.map((o) => (
                            <OverflowItem
                              key={o.label}
                              onClick={() => {
                                setState(item, "snoozed", o.hours);
                                close();
                              }}
                            >
                              Snooze {o.label.toLowerCase()}
                            </OverflowItem>
                          ))}
                          <OverflowItem
                            onClick={() => {
                              setState(item, "dismissed");
                              close();
                            }}
                          >
                            Dismiss
                          </OverflowItem>
                          {item.type === "upcoming_meeting" && (
                            <OverflowItem
                              disabled={meetingBrief.loading && prepItemId === item.id}
                              onClick={() => {
                                prepareFor(item);
                                close();
                              }}
                            >
                              {meetingBrief.loading && prepItemId === item.id ? "Preparing…" : "Prepare me"}
                            </OverflowItem>
                          )}
                          {item.due_at && item.type !== "upcoming_meeting" && (
                            <OverflowItem
                              onClick={() => {
                                proposeCalendar(item);
                                close();
                              }}
                            >
                              Add to calendar
                            </OverflowItem>
                          )}
                          {item.origin === "detected" && (
                            <OverflowItem
                              disabled={investigation.loading && investigateItemId === item.id}
                              onClick={() => {
                                investigateFor(item);
                                close();
                              }}
                            >
                              {investigation.loading && investigateItemId === item.id
                                ? "Investigating…"
                                : "Investigate"}
                            </OverflowItem>
                          )}
                          <OverflowItem
                            onClick={() => {
                              setAskItem(askItem?.id === item.id ? null : item);
                              close();
                            }}
                          >
                            Ask Sentinel
                          </OverflowItem>
                        </>
                      )}
                    </Overflow>
                  </>
                ) : (
                  <button
                    onClick={() => setState(item, "new")}
                    className="text-ink-faint underline underline-offset-2 hover:text-ink"
                  >
                    Reopen
                  </button>
                )}
                <EvidenceLink item={item} className="font-semibold text-accent-text hover:underline" />
              </div>

              {prepItemId === item.id && (meetingBrief.brief || meetingBrief.error) && (
                <div className="mt-3">
                  {meetingBrief.error ? (
                    <p className="text-small text-crit">{meetingBrief.error}</p>
                  ) : (
                    <MeetingBriefPanel
                      brief={meetingBrief.brief!}
                      refreshing={meetingBrief.refreshing}
                      onRefresh={() => meetingBrief.load(`/attention/${item.id}/prepare`, { refresh: true })}
                      onClose={() => {
                        setPrepItemId(null);
                        meetingBrief.clear();
                      }}
                    />
                  )}
                </div>
              )}

              {investigateItemId === item.id && (investigation.investigation || investigation.error) && (
                <div className="mt-3">
                  {investigation.error ? (
                    <p className="text-small text-crit">{investigation.error}</p>
                  ) : (
                    <InvestigationPanel
                      investigation={investigation.investigation!}
                      refreshing={investigation.refreshing}
                      onRefresh={() => investigation.load(`/attention/${item.id}/investigate`, { refresh: true })}
                      onClose={() => {
                        setInvestigateItemId(null);
                        investigation.clear();
                      }}
                    />
                  )}
                </div>
              )}

              {askItem?.id === item.id && (
                <div className="mt-3 border-t border-border pt-3">
                  <SentinelPanel
                    contextLabel="This finding"
                    identity={workspaceContext(active)}
                    contextPrefix={`Regarding this attention item: "${item.title}" (${item.why}).`}
                    placeholder="Why does this matter? What should I do?"
                    suggestions={["Why does this matter?", "What should I do about it?"]}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    );

  // SECTION 9: the Now tab reads top-to-bottom as the spec's flow -
  // findings, then the provider verification that backs them, then the
  // assistant, then the user's own reminders last.
  const nowContent = (
    <div className="flex flex-col gap-6">
      <div>
        <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-micro uppercase tracking-wide text-ink-faint">Findings</h3>
          <div className="flex flex-wrap gap-1">
            {STATE_FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setStateFilter(f.key)}
                className={`rounded-full px-2.5 py-1 font-mono text-micro transition-colors ${
                  stateFilter === f.key ? "bg-surface-3 text-ink" : "text-ink-faint hover:text-ink-dim"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
        {findingsList}
      </div>

      {/* SECTION 4 — standalone only when findings are shown; the all-clear
          state folds providers into its own reassurance instead. */}
      {!showAllClear && <ProvidersChecked status={status} />}

      {/* SECTION 5 */}
      <section>
        <h3 className="mb-2.5 text-micro uppercase tracking-wide text-ink-faint">Sentinel assistant</h3>
        {assistantOpen ? (
          <div className="card p-3.5">
            <SentinelPanel
              contextLabel="Sentinel"
              identity={workspaceContext(active)}
              placeholder="Ask Sentinel about your operations…"
              suggestions={["What needs my attention?", "Summarise what changed today"]}
            />
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-md border border-border px-4 py-3">
            <span className="text-small text-ink-dim">Need help making sense of something?</span>
            <button onClick={() => setAssistantOpen(true)} className="text-small font-medium text-accent-text hover:underline">
              Ask Sentinel
            </button>
          </div>
        )}
      </section>

      {/* SECTION 6: reminders are the user's own notes - below the operational
          findings, never above them, and folded away until wanted. A form
          parked permanently at the bottom of an intelligence feed reads as
          part of the feed, and it was the last thing on a page whose job is
          to be scanned. */}
      <section className="border-t border-rule pt-4">
        {!addingReminder ? (
          <button
            onClick={() => setAddingReminder(true)}
            className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
          >
            + Add a reminder
          </button>
        ) : (
        <form onSubmit={addReminder} className="flex flex-wrap gap-2">
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="e.g. Follow up with the design team"
            className="min-w-0 flex-1 rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-border-strong"
          />
          <input
            type="datetime-local"
            value={newDue}
            onChange={(e) => setNewDue(e.target.value)}
            aria-label="Due (optional)"
            className="rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink outline-none transition-colors focus:border-border-strong"
          />
          <button type="submit" disabled={!newTitle.trim()} className="btn-primary">
            Add
          </button>
          <button
            type="button"
            onClick={() => setAddingReminder(false)}
            className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
          >
            Cancel
          </button>
        </form>
        )}
      </section>
    </div>
  );

  return (
    <div className="max-w-5xl">
      <BackNav back={{ to: "/", label: "Dashboard" }} />
      {/* No subtitle. The verdict card directly below says what this page is
          for, in terms of the user's actual data - a generic restatement above
          it only pushed the real answer further down. */}
      <h1 className="mb-4 text-h2 font-medium text-balance">Attention</h1>

      {/* SECTION 1 — always visible */}
      <SentinelStatusCard status={status} onSync={refresh} syncing={refreshing} />

      {/* The "Today" counter row lived here: Critical / Needs review /
          Reminders / Dismissed. It was the third place the same numbers
          appeared - the verdict card states them in prose above, and the tabs
          carry them as badges below. Three restatements of one fact is what
          made this page feel like a wall. */}

      {error && <p className="mb-4 text-small text-crit">{error}</p>}
      {planResult && (
        <p className={`mb-4 text-small ${planResult.startsWith("Added") ? "text-good" : "text-crit"}`}>{planResult}</p>
      )}
      {plan && (
        <div className="mb-4 rounded-md border border-watch/40 bg-watch/5 p-3.5">
          <div className="label-sub mb-2 font-bold text-watch">Sentinel plans to create this event</div>
          <div className="mb-1 text-body font-semibold text-ink">{plan.plan.title}</div>
          <div className="mb-3 text-caption text-ink-dim">
            {new Date(plan.plan.start).toLocaleString()} — {new Date(plan.plan.end).toLocaleTimeString()}
          </div>
          <div className="flex gap-2">
            <button onClick={confirmCalendar} disabled={planBusy} className="btn-primary">
              {planBusy ? "Adding…" : "Confirm & Add"}
            </button>
            <button
              onClick={() => setPlan(null)}
              disabled={planBusy}
              className="rounded-md border border-border px-3 py-1.5 text-caption text-ink-dim hover:border-crit hover:text-crit disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* SECTION 7 — tabs carry live counts; zero tabs de-emphasise themselves. */}
      <IntelligenceTabs
        scope="personal"
        counts={{ attention: nowCount, ...tabCounts }}
        attention={nowContent}
        autoFocus={focusTab}
      />
    </div>
  );
}
