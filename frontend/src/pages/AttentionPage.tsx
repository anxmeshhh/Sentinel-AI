import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { AttentionItem, CalendarPlan, Commitment, Goal, SentinelStatus, Situation } from "../api/types";
import { BackNav } from "../components/BackNav";
import { SentinelPanel } from "../components/SentinelPanel";
import { workspaceContext } from "../components/context";
import { useWorkspace } from "../context/WorkspaceContext";
import { MeetingBriefPanel, useMeetingBrief } from "../components/MeetingBriefPanel";
import { InvestigationPanel, useInvestigation } from "../components/InvestigationPanel";
import { IntelligenceTabs, type TabKey } from "../components/IntelligenceTabs";
import {
  InsightsList,
  MetricChip,
  RecommendedCard,
  SectionHeader,
  SummaryCard,
} from "../components/assistant/CommandCenter";
import { AssistantFab } from "../components/assistant/AssistantFab";
import { RecentActivity } from "../components/RecentActivity";
import { ContextRail } from "../components/assistant/CommandCenter";
import { openAttention, useIntelligence } from "../hooks/useIntelligence";
import { FindingsEmptyState } from "../components/SentinelStatusPanel";
import {
  Action,
  ActionGroup,
  Icon,
  ActionLink,
  Badge,
  Button,
  ItemList,
  ItemRow,
  LoadingBlock,
  Overflow,
  OverflowItem,
} from "../components/ui";
import type { IconName } from "../components/ui";
import {
  PROVIDER_LABEL,
  ATTENTION_ICON,
  attentionMeta,
  priorityOf,
  dueLabel,
  relativeTime,
} from "../components/situations";

const STATE_FILTERS = [
  { key: "new", label: "Open" },
  { key: "snoozed", label: "Snoozed" },
  { key: "done", label: "Done" },
  { key: "dismissed", label: "Dismissed" },
] as const;

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

/** The tab the page should open on, so the content immediately matches the
 *  narrative verdict: the highest-priority non-empty category. Critical items
 *  live in All (a critical attention item) or Risks (a critical situation) -
 *  open where they actually are. Below critical, the order is the intended
 *  Risks -> Commitments -> Goals -> All, with All as the quiet default. */
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

/** The state filter, as a compact dropdown rather than four permanently
 *  visible chips - it only ever governs the All tab's list, so it sits in
 *  the tab row rather than repeating itself as a second header above the
 *  list every time. */
function FilterMenu({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Overflow
      label="Filter findings"
      align="right"
      trigger={
        <>
          <Icon name="sliders" size={13} /> Filter
        </>
      }
      triggerClassName="inline-flex h-[30px] items-center gap-1.5 rounded-md border border-border px-3 text-caption font-medium text-ink-dim transition-colors hover:border-border-strong hover:text-ink"
    >
      {(close) =>
        STATE_FILTERS.map((f) => (
          <OverflowItem
            key={f.key}
            onClick={() => {
              onChange(f.key);
              close();
            }}
          >
            {f.key === value ? "✓ " : ""}
            {f.label}
          </OverflowItem>
        ))
      }
    </Overflow>
  );
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

  const [newTitle, setNewTitle] = useState("");
  const [newDue, setNewDue] = useState("");

  // The rail, the recommendation, the recent activity and the provider count
  // come from the shared Core hook - the same one the Dashboard and Assistant
  // use, so this page cannot disagree with them. The page's own item loading
  // below is untouched: it owns the state filter and the tab content.
  const intel = useIntelligence();
  const navigate = useNavigate();

  function handOff(question: string) {
    const q = question.trim();
    if (q) navigate(`/assistant?q=${encodeURIComponent(q)}`);
  }

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

  // The All tab holds attention items only - situations live in Risks - so
  // its badge counts attention items, while the verdict and summary count
  // the full operational state (attention + situations) from the backend.
  const nowCount = openItems.filter((i) => i.origin === "detected").length;

  // The all-clear only reassures if the sync genuinely ran. Show it only for
  // the open filter with nothing detected; other filters get a plain
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
      <ItemList>
        {items.map((item) => {
          const src = providerLabel(item.source_provider);
          return (
            <ItemRow
              key={item.id}
              tone={priorityOf(item).tone}
              muted={item.state === "done"}
              title={item.title}
              source={src}
              icon={(ATTENTION_ICON[item.type] as IconName) ?? "alert"}
              // Structured facts, not a sentence. `why` is the sentence and it
              // lives behind the row's "Why" toggle - present for anyone who
              // wants it, not read aloud to everyone who doesn't.
              meta={[
                ...attentionMeta(item),
                item.state === "snoozed" && item.snoozed_until
                  ? `snoozed until ${dueLabel(item.snoozed_until)}`
                  : null,
              ]}
              badge={<Badge tone={priorityOf(item).tone}>{priorityOf(item).label}</Badge>}
              details={item.why}
              className={askItem?.id === item.id ? "bg-surface/60" : undefined}
              actions={
                <ActionGroup>
                  {item.state === "new" ? (
                    <>
                      <Action kind="done" onClick={() => setState(item, "done")} />
                      {/* A labelled dropdown, not a bare button - the choice
                          of duration is real functionality, so it stays one
                          click away rather than defaulting silently. */}
                      <Overflow
                        label="Snooze"
                        trigger={
                          <>
                            <Icon name="clock" size={13} /> Snooze
                          </>
                        }
                        triggerClassName="inline-flex h-[30px] items-center gap-1.5 rounded-md border !border-watch/35 px-3 text-caption font-medium !text-watch transition-colors hover:!border-watch/60 hover:!bg-watch/10"
                      >
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
                                {o.label}
                              </OverflowItem>
                            ))}
                          </>
                        )}
                      </Overflow>
                      {item.evidence_url && <ActionLink kind="open" to={item.evidence_url} />}
                      <Overflow label="More actions">
                        {(close) => (
                          <>
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
                    <>
                      <Action kind="undo" label="Reopen" onClick={() => setState(item, "new")} />
                      {item.evidence_url && <ActionLink kind="open" to={item.evidence_url} />}
                    </>
                  )}
                </ActionGroup>
              }
            >
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
            </ItemRow>
          );
        })}
      </ItemList>
    );

  // The All tab reads top to bottom: findings first, then anything genuinely
  // awaiting a decision, then the user's own reminders last. Providers-
  // checked and the free-text composer both moved out - the first duplicated
  // the top metric chips, the second duplicated the Assistant.
  const nowContent = (
    <div className="flex flex-col gap-6">
      <div>
        <SectionHeader title="Needs your attention" count={items.length} />
        {findingsList}
      </div>

      {/* Reminders are the user's own notes - below the operational findings,
          never above them, and folded away until wanted. */}
      <section className="border-t border-rule pt-4">
        {!addingReminder ? (
          <Action kind="create" label="Add a reminder" onClick={() => setAddingReminder(true)} />
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
            <Button size="sm" variant="primary" type="submit" disabled={!newTitle.trim()}>
              Add
            </Button>
            <Action kind="cancel" onClick={() => setAddingReminder(false)} />
          </form>
        )}
      </section>
    </div>
  );

  // Summary counts, all derived from data already loaded - nothing new is
  // fetched and nothing is invented. A card with a zero count does not render.
  // Counted from the shared Core hook, not this page's own list, so the
  // summary here can never disagree with the same numbers on the Dashboard.
  // `priorityOf` is the one place the four-step scale is defined.
  const openNow = openAttention(intel.attention);
  const criticalCount = openNow.filter((i) => priorityOf(i).label === "Critical").length;
  const upcomingCount = openNow.filter(
    (i) => i.due_at && new Date(i.due_at).getTime() > Date.now(),
  ).length;
  const insightCount = intel.memories.length;

  return (
    <div className="flex gap-6">
      <div className="flex min-w-0 flex-1 flex-col">
        <BackNav back={{ to: "/", label: "Dashboard" }} />

        <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-h2 font-semibold tracking-tight text-ink">Attention</h1>
            <p className="mt-1 text-small text-ink-dim">Here's what needs your immediate attention.</p>
          </div>
          <Button size="sm" variant="secondary" loading={refreshing} onClick={() => void refresh()}>
            <Icon name="refresh" size={13} /> Sync now
          </Button>
        </header>

        {/* The verdict card's numbers, as chips. Same source, a fraction of
            the height - this page is scanned, not read. */}
        {status && (
          <div className="mb-5 flex flex-wrap gap-2">
            <MetricChip icon="activity" label="Signals" value={status.signals_analysed.toLocaleString()} />
            <MetricChip icon="layers" label="Services" value={status.provider_count} />
            <MetricChip icon="grid" label="Providers" value={intel.connections.length} />
            {status.last_synced_at && (
              <MetricChip icon="check" label="Synced" value={relativeTime(status.last_synced_at)} tone="good" />
            )}
          </div>
        )}

        {(criticalCount > 0 || upcomingCount > 0 || insightCount > 0) && (
          <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {criticalCount > 0 && (
              <SummaryCard
                tone="critical"
                label="Critical"
                count={criticalCount}
                description={criticalCount === 1 ? "critical risk" : "critical risks"}
                to="/findings"
              />
            )}
            {upcomingCount > 0 && (
              <SummaryCard
                tone="upcoming"
                label="Upcoming"
                count={upcomingCount}
                description={upcomingCount === 1 ? "upcoming item" : "upcoming items"}
                to="/attention"
              />
            )}
            {insightCount > 0 && (
              <SummaryCard
                tone="insight"
                label="Insight"
                count={insightCount}
                description={insightCount === 1 ? "pattern detected" : "patterns detected"}
                to="/memory"
              />
            )}
          </div>
        )}

        {error && <p className="mb-4 text-small text-crit">{error}</p>}
        {planResult && (
          <p className={`mb-4 text-small ${planResult.startsWith("Added") ? "text-good" : "text-crit"}`}>
            {planResult}
          </p>
        )}
        {plan && (
          <div className="mb-4 rounded-lg border border-warn/40 bg-warn/5 p-3.5">
            <div className="mb-2 text-micro font-semibold uppercase tracking-wide text-warn">
              Sentinel plans to create this event
            </div>
            <div className="mb-1 text-small font-semibold text-ink">{plan.plan.title}</div>
            <div className="mb-3 text-caption text-ink-dim">
              {new Date(plan.plan.start).toLocaleString()} — {new Date(plan.plan.end).toLocaleTimeString()}
            </div>
            <ActionGroup>
              <Action kind="confirm" label="Confirm & add" loading={planBusy} onClick={() => void confirmCalendar()} />
              <Action kind="cancel" onClick={() => setPlan(null)} disabled={planBusy} />
            </ActionGroup>
          </div>
        )}

        {/* Tabs carry live counts; zero tabs de-emphasise themselves. The
            state filter lives in the Filter control at the tab row's right
            edge rather than as its own permanently-visible chip row. */}
        <IntelligenceTabs
          scope="personal"
          counts={{ attention: nowCount, ...tabCounts, insights: intel.memories.length }}
          attention={nowContent}
          insights={<InsightsList memories={intel.memories} />}
          autoFocus={focusTab}
          compact
          filterSlot={<FilterMenu value={stateFilter} onChange={setStateFilter} />}
        />

        <RecommendedCard
          decision={intel.decisions.find((d) => d.kind === "recommend") ?? intel.decisions[0]}
          onDecide={async (id, verb) => {
            intel.dropDecision(id);
            await api.post(`/decisions/${id}/${verb}`).catch(() => void intel.reload());
          }}
        />

        <RecentActivity scope="personal" />
      </div>

      <ContextRail intel={intel} onAsk={handOff} />

      {/* The way in to the Assistant - it owns every capability, so this is a
          shortcut to it rather than a second surface that duplicates it. */}
      <AssistantFab />
    </div>
  );
}
