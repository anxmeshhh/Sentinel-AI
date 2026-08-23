import type React from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { AttentionItem, DecisionRow, MemoryRow } from "../../api/types";
import type { Intelligence } from "../../hooks/useIntelligence";
import { PROVIDER_GLYPH } from "../ProviderIcons";
import { SituationCard } from "../SituationCard";
import {
  ATTENTION_ICON,
  PROVIDER_LABEL,
  attentionMeta,
  dueLabel,
  priorityOf,
  relativeTime,
} from "../situations";
import {
  Action,
  ActionGroup,
  ActionLink,
  Badge,
  Icon,
  ItemList,
  ItemRow,
  Spinner,
  type IconName,
} from "../ui";
import { SUGGESTIONS } from "./intent";
import { SignalCard } from "./SignalCard";

/**
 * The Command Center, as parts.
 *
 * The Dashboard and the Assistant answer the same question - what matters, why,
 * and what should I do - so they render the same things. Keeping these in one
 * module is what stops the two surfaces drifting into two products: a change to
 * how a finding row looks lands on both, and neither can quietly disagree with
 * the other about priority, wording or which action a row offers.
 *
 * Nothing here fetches or decides. Every component takes what the engines
 * already wrote (via useIntelligence) and renders it; when there is nothing,
 * it renders nothing rather than a placeholder.
 */

/* ------------------------------------------------------------- header -- */

export function Greeting({
  name,
  subtitle,
  onSearchFocus,
}: {
  name?: string | null;
  subtitle: string;
  onSearchFocus?: () => void;
}) {
  return (
    <header className="mb-4 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-h2 font-semibold tracking-tight text-ink">
          {timeGreeting()}
          {name ? `, ${name.split(" ")[0]}` : ""} <span aria-hidden="true">👋</span>
        </h1>
        <p className="mt-1 text-small text-ink-dim">{subtitle}</p>
      </div>

      {onSearchFocus && (
        <button
          type="button"
          onClick={onSearchFocus}
          className="hidden min-w-[280px] items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-caption text-ink-faint transition-colors hover:border-border-strong lg:flex"
        >
          <Icon name="search" size={14} />
          <span className="flex-1 text-left">Ask Sentinel anything…</span>
          <kbd className="rounded border border-border px-1.5 py-0.5 text-micro text-ink-faint">⌘K</kbd>
        </button>
      )}
    </header>
  );
}

/** Signals, services, providers and last sync - all from /attention/status. */
export function StatChips({ intel }: { intel: Intelligence }) {
  const { status } = intel;
  if (!status) return null;

  return (
    <div className="mb-5 flex flex-wrap gap-1.5">
      <StatChip icon="activity">{status.signals_analysed.toLocaleString()} signals</StatChip>
      <StatChip icon="layers">
        {status.provider_count} {status.provider_count === 1 ? "service" : "services"}
      </StatChip>
      <StatChip icon="grid">
        {intel.connections.length} {intel.connections.length === 1 ? "provider" : "providers"}
      </StatChip>
      {status.last_synced_at && (
        <StatChip dot="good">Synced {relativeTime(status.last_synced_at)}</StatChip>
      )}
    </div>
  );
}

export function StatChip({
  children,
  dot,
  icon,
}: {
  children: ReactNode;
  dot?: "good";
  icon?: IconName;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-micro text-ink-faint">
      {dot === "good" && <span className="h-1.5 w-1.5 rounded-full bg-good" aria-hidden="true" />}
      {icon && !dot && <Icon name={icon} size={12} />}
      {children}
    </span>
  );
}

/**
 * A labelled metric: `Signals 388`.
 *
 * Distinct from StatChip, which reads as a sentence fragment ("388 signals").
 * On a page whose job is scanning, the label and the number want to be two
 * separate things the eye can land on.
 */
export function MetricChip({
  icon,
  label,
  value,
  tone,
}: {
  icon: IconName;
  label: string;
  value: ReactNode;
  tone?: "good";
}) {
  return (
    <span className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-1.5">
      <Icon
        name={icon}
        size={13}
        className={tone === "good" ? "flex-none text-good" : "flex-none text-accent-text"}
      />
      <span className="text-micro text-ink-faint">{label}</span>
      <span className="text-caption font-semibold text-ink">{value}</span>
    </span>
  );
}

/**
 * A count-led summary card: "2 Critical risks".
 *
 * The number is the headline because these cards answer "how much", not
 * "which one" - that is what the list below them is for. Renders only when
 * there is something to count; a card reading "0 Critical risks" is a fact
 * nobody needs stated in 200px of chrome.
 */
export function SummaryCard({
  tone,
  label,
  count,
  description,
  to,
}: {
  tone: "critical" | "upcoming" | "insight";
  label: string;
  count: number;
  description: string;
  to: string;
}) {
  const style = {
    critical: { chip: "text-crit", ring: "border-crit/30 bg-crit/[0.06]", icon: "alert" as IconName },
    upcoming: { chip: "text-warn", ring: "border-warn/30 bg-warn/[0.06]", icon: "clock" as IconName },
    insight: { chip: "text-good", ring: "border-good/30 bg-good/[0.06]", icon: "brain" as IconName },
  }[tone];

  return (
    <div className={`flex flex-col rounded-lg border p-4 ${style.ring}`}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className={`text-micro font-semibold uppercase tracking-wide ${style.chip}`}>{label}</span>
        <Icon name={style.icon} size={15} className={style.chip} />
      </div>
      <p className="flex items-baseline gap-2">
        <span className="text-h2 font-semibold leading-none text-ink">{count}</span>
        <span className="text-small text-ink-dim">{description}</span>
      </p>
      <Link
        to={to}
        className={`mt-auto pt-3 text-caption font-medium ${style.chip} inline-flex items-center gap-1`}
      >
        View all <span aria-hidden="true">→</span>
      </Link>
    </div>
  );
}

/* -------------------------------------------------------------- cards -- */

/**
 * Critical / Upcoming / Insight.
 *
 * Each card is one thing the Core concluded: the top open Situation, the next
 * upcoming meeting, and the most recent Memory. Fewer than three render when
 * fewer than three exist - a card invented to fill the row would be exactly the
 * fabrication the architecture exists to prevent.
 */
export function SignalCards({
  intel,
  open,
  onPrepare,
  busy,
}: {
  intel: Intelligence;
  open: AttentionItem[];
  onPrepare: () => void;
  busy?: boolean;
}) {
  const situation = intel.situations[0];
  const meeting = open.find((i) => i.type === "upcoming_meeting");
  const memory = intel.memories[0];

  if (!situation && !meeting && !memory) return null;

  return (
    <div className="mb-6 grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
      {situation && (
        <SignalCard
          tone="critical"
          title={situation.entity ?? situation.title}
          body={`${situation.member_count} related finding${
            situation.member_count === 1 ? "" : "s"
          } across ${situation.providers.length} service${situation.providers.length === 1 ? "" : "s"}.`}
          meta={
            <div className="flex flex-wrap gap-1">
              {situation.providers.slice(0, 3).map((p) => (
                <Badge key={p} tone="outline">
                  {PROVIDER_LABEL[p] ?? p}
                </Badge>
              ))}
            </div>
          }
          actionLabel="View situation"
          to={`/situations/${situation.id}`}
        />
      )}

      {meeting && (
        <SignalCard
          tone="upcoming"
          title={meeting.title}
          // The engine writes `why` at sync time, so after a stale sync it
          // contradicts the timing computed from due_at. Trust the timestamp.
          body={
            dueLabel(meeting.due_at, "meeting")
              ? `This meeting ${dueLabel(meeting.due_at, "meeting")}.`
              : meeting.why
          }
          meta={
            meeting.source_provider ? (
              <Badge tone="outline">
                {PROVIDER_LABEL[meeting.source_provider] ?? meeting.source_provider}
              </Badge>
            ) : undefined
          }
          actionLabel="Prepare me"
          busy={busy}
          onAction={onPrepare}
        />
      )}

      {memory && (
        <SignalCard
          tone="insight"
          title="Recurring pattern"
          body={memory.summary}
          meta={
            <Badge tone="outline">
              Seen {memory.observation_count} time{memory.observation_count === 1 ? "" : "s"}
            </Badge>
          }
          actionLabel="View memory"
          to="/memory"
        />
      )}
    </div>
  );
}

/* ----------------------------------------------------------- findings -- */

export function AttentionSection({
  items,
  total,
  onResolve,
}: {
  items: AttentionItem[];
  total: number;
  onResolve: (i: AttentionItem, s: "done" | "snoozed") => void;
}) {
  if (items.length === 0) return null;

  return (
    <section className="mb-6">
      <SectionHeader title="Needs your attention" count={total} to="/attention" />
      <AttentionRows items={items} onResolve={onResolve} />
    </section>
  );
}

/**
 * A title, a count pill, and an optional "View all" link - the one heading
 * shape used above every list in the product (findings, activity, insights),
 * so a page never grows a second way to introduce "here are N things".
 */
export function SectionHeader({
  title,
  count,
  to,
  toLabel = "View all",
}: {
  title: string;
  count?: number;
  to?: string;
  toLabel?: string;
}) {
  return (
    <div className="mb-2 flex items-baseline justify-between gap-2">
      <h2 className="flex items-center gap-2 text-small font-semibold text-ink">
        {title}
        {count !== undefined && (
          <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-micro text-ink-dim">{count}</span>
        )}
      </h2>
      {to && (
        <Link to={to} className="text-caption text-ink-faint transition-colors hover:text-ink">
          {toLabel} →
        </Link>
      )}
    </div>
  );
}

/** Memory, as a list - the Insights tab's content. Read-only: a memory is
 *  something Sentinel concluded from recurrence, not something a person
 *  edits here. Empty state names the mechanism rather than apologising,
 *  since "none yet" is the correct state for a quiet workspace. */
export function InsightsList({ memories }: { memories: MemoryRow[] }) {
  if (memories.length === 0) {
    return (
      <p className="text-caption text-ink-faint">
        Nothing learned yet. A pattern appears here once the same situation happens more than once.
      </p>
    );
  }
  return (
    <ItemList>
      {memories.map((m) => (
        <ItemRow
          key={m.id}
          tone="good"
          icon="brain"
          title={m.summary}
          meta={[
            `Seen ${m.observation_count} time${m.observation_count === 1 ? "" : "s"}`,
            m.last_observed_at ? `last ${relativeTime(m.last_observed_at)}` : null,
          ]}
        />
      ))}
    </ItemList>
  );
}

export function AttentionRows({
  items,
  onResolve,
}: {
  items: AttentionItem[];
  onResolve: (i: AttentionItem, s: "done" | "snoozed") => void;
}) {
  return (
    <ItemList>
      {items.map((item) => (
        <ItemRow
          key={item.id}
          tone={priorityOf(item).tone}
          title={item.title}
          source={
            item.source_provider
              ? (PROVIDER_LABEL[item.source_provider] ?? item.source_provider)
              : "Sentinel"
          }
          meta={attentionMeta(item)}
          badge={<Badge tone={priorityOf(item).tone}>{priorityOf(item).label}</Badge>}
          icon={(ATTENTION_ICON[item.type] as IconName) ?? "alert"}
          details={item.why}
          actions={
            <ActionGroup>
              <Action kind="done" onClick={() => onResolve(item, "done")} />
              <Action kind="snooze" onClick={() => onResolve(item, "snoozed")} />
              {item.evidence_url && <ActionLink kind="open" to={item.evidence_url} />}
            </ActionGroup>
          }
        />
      ))}
    </ItemList>
  );
}

/* -------------------------------------------------------- recommended -- */

/** The Decision Engine's own recommendation. Renders nothing when it has not
 *  made one - there is no "no recommendation" placeholder, because a decision
 *  invented to fill the slot would not be grounded in anything. */
export function RecommendedCard({
  decision,
  busy,
  onDecide,
}: {
  decision: DecisionRow | undefined;
  busy?: boolean;
  onDecide: (id: string, verb: "confirm" | "dismiss") => void;
}) {
  if (!decision) return null;

  return (
    <section className="mb-6 rounded-lg border border-accent/25 bg-accent/[0.05] p-4">
      <div className="mb-1.5 flex items-center gap-1.5 text-micro font-semibold uppercase tracking-wide text-accent-text">
        <Icon name="sparkle" size={13} /> Recommended next step
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-small font-medium text-ink">{decision.action}</p>
          <p className="mt-0.5 text-caption text-ink-faint">{decision.rationale}</p>
        </div>
        <ActionGroup>
          {decision.kind === "recommend" ? (
            <>
              <Action kind="confirm" loading={busy} onClick={() => onDecide(decision.id, "confirm")} />
              <Action kind="dismiss" onClick={() => onDecide(decision.id, "dismiss")} />
            </>
          ) : (
            <Action kind="dismiss" label="Got it" onClick={() => onDecide(decision.id, "dismiss")} />
          )}
        </ActionGroup>
      </div>
    </section>
  );
}

/* ----------------------------------------------------------- composer -- */

export function Composer({
  value,
  onChange,
  onSubmit,
  busy,
  showSuggestions,
  onSuggest,
  inputRef,
  sticky = true,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
  showSuggestions: boolean;
  onSuggest: (s: string) => void;
  inputRef?: React.RefObject<HTMLInputElement>;
  /** Pinned on the Assistant, where it is the primary surface and the conversation
   *  scrolls beneath it. In normal flow on the Dashboard, where pinning it
   *  would float the input over the findings list it sits below. */
  sticky?: boolean;
}) {
  return (
    <div
      className={
        sticky
          ? "sticky bottom-0 -mx-1 flex-none bg-ground px-1 pb-3 pt-3"
          : "mt-2 flex-none pb-1"
      }
    >
      <div className="rounded-lg border border-border bg-surface px-3 py-2.5 transition-colors focus-within:border-border-strong">
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSubmit()}
          placeholder="Ask Sentinel anything…"
          className="w-full bg-transparent text-small text-ink outline-none placeholder:text-ink-faint"
        />
        <div className="mt-2 flex items-center justify-between gap-2">
          <span
            className="flex h-7 w-7 items-center justify-center rounded-md border border-border text-ink-faint"
            aria-hidden="true"
          >
            <Icon name="plus" size={14} />
          </span>
          <div className="flex items-center gap-2">
            <Icon name="mic" size={15} className="text-ink-faint" />
            <button
              type="button"
              onClick={onSubmit}
              disabled={busy || !value.trim()}
              aria-label="Send"
              className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-white transition-colors hover:bg-accent-hover disabled:opacity-40"
            >
              {busy ? <Spinner size="sm" /> : <Icon name="send" size={14} />}
            </button>
          </div>
        </div>
      </div>

      {showSuggestions && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((s) => (
            <Chip key={s} onClick={() => onSuggest(s)}>
              {s}
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

export function Chip({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-caption text-ink-dim transition-colors hover:border-border-strong hover:text-ink"
    >
      {children}
    </button>
  );
}

/* --------------------------------------------------------------- rail -- */

const QUICK_ACTIONS: { label: string; ask: string; icon: IconName }[] = [
  { label: "Catch me up", ask: "What did I miss?", icon: "activity" },
  { label: "What needs my attention?", ask: "What needs my attention?", icon: "alert" },
  { label: "Prepare me for my next meeting", ask: "Prepare me for my next meeting", icon: "calendar" },
  { label: "Ask anything", ask: "What do you remember?", icon: "brain" },
];

/** Memory, watching, and the situation currently in play. Short blocks only -
 *  the rail carries state, not explanation. */
export function ContextRail({ intel, onAsk }: { intel: Intelligence; onAsk: (q: string) => void }) {
  const situation = intel.situations[0];

  return (
    <aside className="hidden w-[268px] flex-none flex-col gap-3 self-start xl:flex">
      <div className="sticky top-0 flex flex-col gap-3">
        {situation && (
          <RailPanel title="Context" icon="sliders">
            <RailBlock label="Active situation" to="/situations">
              <SituationCard situation={situation} compact />
            </RailBlock>
          </RailPanel>
        )}

        <MemoryRailPanel memory={intel.memories[0]} />
        <WatchingRailPanel intel={intel} />

        {/* Each is a real capability, phrased the way the Assistant's router
            recognises it - the buttons and the parser cannot drift apart. */}
        <RailPanel title="Quick actions">
          <div className="flex flex-col gap-1.5 p-3">
            {QUICK_ACTIONS.map((q) => (
              <button
                key={q.label}
                type="button"
                onClick={() => onAsk(q.ask)}
                className="flex items-center gap-2 rounded-md border border-border px-2.5 py-2 text-left text-caption text-ink-dim transition-colors hover:border-border-strong hover:text-ink"
              >
                <Icon name={q.icon} size={13} className="flex-none text-ink-faint" />
                <span className="truncate">{q.label}</span>
              </button>
            ))}
          </div>
        </RailPanel>
      </div>
    </aside>
  );
}

/** The rail's Memory block - one function, so the Command Center and
 *  Situations rails can never show a memory summary differently. */
function MemoryRailPanel({ memory }: { memory: MemoryRow | undefined }) {
  if (!memory) return null;
  return (
    <RailPanel title="Memory" to="/memory">
      <div className="flex gap-2.5 p-3">
        <span
          className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-accent/15 text-accent-text"
          aria-hidden="true"
        >
          <Icon name="brain" size={14} />
        </span>
        <div className="min-w-0">
          <p className="line-clamp-3 text-caption leading-relaxed text-ink-dim">{memory.summary}</p>
          <p className="mt-1 text-micro text-ink-faint">Last seen {relativeTime(memory.last_observed_at)}</p>
        </div>
      </div>
    </RailPanel>
  );
}

/** The rail's Watching block - connection health and goal progress. Renders
 *  nothing for zero connections rather than an empty state wearing a
 *  heading. */
function WatchingRailPanel({ intel }: { intel: Intelligence }) {
  if (intel.connections.length === 0) return null;
  const errors = intel.status?.errors.length ?? 0;
  const onTrack = intel.goals.filter((g) => g.health === "on_track").length;

  return (
    <RailPanel title="Watching" to="/settings">
      <div className="flex flex-col gap-2.5 p-3">
        <RailStat
          tone={errors > 0 ? "crit" : "good"}
          icon="check"
          value={`${intel.connections.length} connection${intel.connections.length === 1 ? "" : "s"}`}
          note={errors > 0 ? `${errors} need attention` : "All healthy"}
        />
        {intel.goals.length > 0 && (
          <RailStat
            tone="good"
            icon="target"
            value={`${intel.goals.length} goal${intel.goals.length === 1 ? "" : "s"}`}
            note={`${onTrack} on track`}
          />
        )}
      </div>
    </RailPanel>
  );
}

/**
 * The Situations page's rail: what the most pressing open situation
 * concerns, which services it spans, what Sentinel remembers, and what it's
 * watching. "What this concerns" and "Services involved" are the top open
 * situation's own fields (the same one the list's first card describes) -
 * there is no per-card rail on a list of several, so this names the one
 * that would need you first. Each block renders only when it has something
 * real to show.
 */
export function SituationsRail({ intel }: { intel: Intelligence }) {
  const situation = intel.situations[0];

  return (
    <aside className="hidden w-[268px] flex-none flex-col gap-3 self-start xl:flex">
      <div className="sticky top-0 flex flex-col gap-3">
        {situation && (
          <RailPanel title="What this concerns" to="/situations">
            <div className="px-3 pb-3">
              <p className="text-caption text-ink-dim">
                <span className="text-micro text-ink-faint">{situation.entity_kind ?? "resource"}</span>{" "}
                {situation.entity ?? situation.title}
              </p>
            </div>
          </RailPanel>
        )}

        {situation && situation.providers.length > 0 && (
          <RailPanel title="Services involved">
            <ul className="flex flex-col gap-2 px-3 pb-3">
              {situation.providers.map((p) => {
                const Glyph = PROVIDER_GLYPH[p];
                return (
                  <li key={p} className="flex items-center gap-2 text-caption text-ink-dim">
                    <span className="flex h-5 w-5 flex-none items-center justify-center rounded-sm" aria-hidden="true">
                      {Glyph ? <Glyph /> : null}
                    </span>
                    {PROVIDER_LABEL[p] ?? p}
                  </li>
                );
              })}
            </ul>
          </RailPanel>
        )}

        <MemoryRailPanel memory={intel.memories[0]} />
        <WatchingRailPanel intel={intel} />
      </div>
    </aside>
  );
}

export function RailPanel({
  title,
  to,
  icon,
  children,
}: {
  title: string;
  to?: string;
  icon?: IconName;
  children: ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between gap-2 px-3.5 py-2.5">
        <h2 className="text-micro font-semibold uppercase tracking-wide text-ink-faint">{title}</h2>
        {to ? (
          <Link to={to} className="text-micro text-ink-faint transition-colors hover:text-ink">
            View all →
          </Link>
        ) : (
          icon && <Icon name={icon} size={13} className="text-ink-faint" />
        )}
      </div>
      {children}
    </div>
  );
}

function RailBlock({ label, to, children }: { label: string; to?: string; children: ReactNode }) {
  return (
    <div className="p-3 pt-0">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="text-caption text-ink-dim">{label}</h3>
        {to && (
          <Link to={to} className="text-micro text-ink-faint transition-colors hover:text-ink">
            View all →
          </Link>
        )}
      </div>
      {children}
    </div>
  );
}

function RailStat({
  tone,
  icon,
  value,
  note,
}: {
  tone: "good" | "crit";
  icon: IconName;
  value: string;
  note: string;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <span
        className={`flex h-7 w-7 flex-none items-center justify-center rounded-full ${
          tone === "crit" ? "bg-crit/15 text-crit" : "bg-good/15 text-good"
        }`}
        aria-hidden="true"
      >
        <Icon name={icon} size={13} />
      </span>
      <div className="min-w-0">
        <p className="truncate text-caption font-medium text-ink">{value}</p>
        <p className={`truncate text-micro ${tone === "crit" ? "text-crit" : "text-ink-faint"}`}>{note}</p>
      </div>
    </div>
  );
}

export function timeGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}
