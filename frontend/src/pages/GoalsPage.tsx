import type { FormEvent, ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Commitment, Goal, GoalDetail } from "../api/types";
import { BackNav } from "../components/BackNav";
import { InvestigationPanel, useInvestigation } from "../components/InvestigationPanel";
import { Modal } from "../components/Modal";
import { dueLabel } from "../components/situations";
import { useWorkspace } from "../context/WorkspaceContext";
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Icon,
  Input,
  ItemList,
  ItemRow,
  PageHeader,
  SkeletonRows,
  TabBar,
  Textarea,
  type TabBarItem,
  type Tone,
} from "../components/ui";

/**
 * Goals - same shell as Attention, Situations and Findings: a BackNav, a
 * compact header, an underline TabBar for state. Like those pages, a row
 * collapses to what you can scan (title, outcome, due date, progress,
 * health) and expands into the reasoning behind it - nothing here recomputes
 * or invents that reasoning, it is GoalDetail read verbatim.
 *
 * The row header already says WHAT (title + outcome), PROGRESS and HEALTH
 * (badge) - so the expanded panel does not repeat them. It continues the
 * flow: WHY (health_reasons) -> AT RISK (blockers/risks) -> NEXT
 * (assessment/next_step) -> the linked evidence and lifecycle actions.
 */
const HEALTH: Record<Goal["health"], { label: string; tone: Tone }> = {
  on_track: { label: "On track", tone: "good" },
  at_risk: { label: "At risk", tone: "warn" },
  blocked: { label: "Blocked", tone: "crit" },
  achieved: { label: "Achieved", tone: "good" },
  abandoned: { label: "Abandoned", tone: "neutral" },
  unknown: { label: "Cannot yet be determined", tone: "neutral" },
};

type TabKey = "open" | "closed";

export function GoalsPage() {
  const { active } = useWorkspace();
  const [rows, setRows] = useState<Goal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState<TabKey>("open");
  // Which goal's detail is expanded in place.
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.get<Goal[]>("/goals?include_closed=true"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load goals");
      setRows([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, active?.id]);

  const open = (rows ?? []).filter((g) => !g.closed_at);
  const closed = (rows ?? []).filter((g) => g.closed_at);
  const visible = tab === "open" ? open : closed;

  function toggle(id: string) {
    setOpenId((current) => (current === id ? null : id));
  }

  const tabs: TabBarItem<TabKey>[] = [
    { key: "open", label: "Open", count: open.length },
    { key: "closed", label: "Closed", count: closed.length },
  ];

  const newGoalButton = (
    <Button variant="primary" onClick={() => setCreating(true)}>
      <Icon name="plus" size={13} /> New Goal
    </Button>
  );

  return (
    <div>
      <BackNav back={{ to: "/", label: "Dashboard" }} />

      <PageHeader
        title="Goals"
        description="What you're working towards, and how Sentinel currently reads each one."
        actions={newGoalButton}
      />

      <TabBar items={tabs} value={tab} onChange={setTab} />

      {error && <p className="mb-4 text-caption text-crit">{error}</p>}

      {rows === null ? (
        <SkeletonRows rows={3} />
      ) : visible.length === 0 ? (
        <EmptyState
          title={
            tab === "open"
              ? open.length === 0 && closed.length > 0
                ? "Nothing open right now."
                : "No goals yet."
              : "Nothing closed yet."
          }
          description={
            tab === "open"
              ? "Goals give Sentinel something to measure activity against - set one to see whether it's actually on track, and why."
              : "Goals you achieve or abandon show up here, never deleted outright."
          }
          action={tab === "open" ? newGoalButton : undefined}
        />
      ) : (
        <ItemList>
          {visible.map((g) => (
            <GoalRow
              key={g.id}
              goal={g}
              closed={tab === "closed"}
              expanded={openId === g.id}
              onToggle={() => toggle(g.id)}
              onChanged={load}
            />
          ))}
        </ItemList>
      )}

      {creating && (
        <NewGoalModal
          onClose={() => setCreating(false)}
          onCreated={async (goal) => {
            setCreating(false);
            await load();
            // "Immediately show the newly created goal" - land on its
            // (still-UNKNOWN) assessment rather than making the user find it.
            setOpenId(goal.id);
          }}
        />
      )}
    </div>
  );
}

function NewGoalModal({ onClose, onCreated }: { onClose: () => void; onCreated: (goal: Goal) => void | Promise<void> }) {
  const [title, setTitle] = useState("");
  const [outcome, setOutcome] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (title.trim().length < 2) {
      setError("Give the goal a title.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      // The one write call this page makes - the existing POST /goals,
      // unchanged. Everything about health/progress is decided server-side.
      const goal = await api.post<Goal>("/goals", {
        title: title.trim(),
        outcome: outcome.trim() || null,
        due_at: due ? new Date(due).toISOString() : null,
      });
      await onCreated(goal);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't create that goal.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="New goal" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Title" htmlFor="goal-title">
          <Input
            id="goal-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Launch Product V2"
            autoFocus
          />
        </Field>
        <Field
          label="Desired outcome"
          hint={'What does "done" look like? This is what Sentinel reasons about, not the title.'}
        >
          <Textarea
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
            placeholder="Shipped to all customers, no P0 bugs in the first week"
            rows={3}
          />
        </Field>
        <Field label="Due date" hint="Optional.">
          <Input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </Field>

        {error && <p className="text-caption text-crit">{error}</p>}

        <div className="mt-1 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={busy}>
            Create Goal
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function GoalRow({
  goal: g,
  expanded,
  onToggle,
  onChanged,
  closed = false,
}: {
  goal: Goal;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => Promise<void>;
  closed?: boolean;
}) {
  const health = HEALTH[g.health] ?? HEALTH.unknown;
  return (
    <ItemRow
      tone={closed ? "neutral" : health.tone}
      muted={closed}
      icon="target"
      title={g.title}
      // WHAT + PROGRESS, scannable without opening the row.
      meta={[
        g.outcome,
        dueLabel(g.due_at),
        g.progress !== null ? `${Math.round(g.progress * 100)}% complete` : "Progress not yet measurable",
      ]}
      // HEALTH / STATUS - the engine's own value, never re-derived here.
      badge={<Badge tone={closed ? "neutral" : health.tone}>{health.label}</Badge>}
      actions={
        <Button size="sm" variant="ghost" onClick={onToggle}>
          {expanded ? "Hide" : "Open"}
        </Button>
      }
    >
      {expanded && <GoalExpanded goalId={g.id} onChanged={onChanged} />}
    </ItemRow>
  );
}

/**
 * The Goal detail/panel: WHY -> AT RISK -> NEXT, then the evidence behind the
 * assessment and the actions the Goal API already supported. Continues the
 * flow the row header started (WHAT/PROGRESS/HEALTH) rather than repeating
 * it - opening a goal should add information, not restate the row.
 */
function GoalExpanded({ goalId, onChanged }: { goalId: string; onChanged: () => Promise<void> }) {
  const [detail, setDetail] = useState<GoalDetail | null>(null);
  const [linkable, setLinkable] = useState<Commitment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const investigation = useInvestigation();
  const [investigating, setInvestigating] = useState(false);

  const load = useCallback(async () => {
    try {
      const [d, c] = await Promise.all([
        api.get<GoalDetail>(`/goals/${goalId}?refresh=true`),
        api.get<Commitment[]>("/commitments"),
      ]);
      setDetail(d);
      setLinkable(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load this goal.");
    }
  }, [goalId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function link(commitmentId: string) {
    setBusy(true);
    try {
      setDetail(await api.post<GoalDetail>(`/goals/${goalId}/commitments`, { commitment_id: commitmentId }));
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function unlink(commitmentId: string) {
    setBusy(true);
    try {
      setDetail(await api.delete<GoalDetail>(`/goals/${goalId}/commitments/${commitmentId}`));
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function setWeight(commitmentId: string, weight: number) {
    setBusy(true);
    try {
      setDetail(await api.patch<GoalDetail>(`/goals/${goalId}/commitments/${commitmentId}`, { weight }));
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function classify(situationId: string, relation: string) {
    setBusy(true);
    try {
      setDetail(
        await api.post<GoalDetail>(`/goals/${goalId}/situations`, { situation_id: situationId, relation }),
      );
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function close(action: "achieved" | "abandoned" | "reopen") {
    setBusy(true);
    try {
      await api.post(`/goals/${goalId}/${action}`);
      // Refetches this goal's own detail (health/reasons/closed_at all
      // change) as well as the page's list, so state stays consistent even
      // though the row will leave the current tab once `onChanged` resolves.
      await Promise.all([load(), onChanged()]);
    } finally {
      setBusy(false);
    }
  }

  function investigate() {
    if (investigating) {
      setInvestigating(false);
      investigation.clear();
      return;
    }
    setInvestigating(true);
    void investigation.load(`/goals/${goalId}/investigate`);
  }

  if (error) return <p className="border-t border-border pt-3 text-caption text-crit">{error}</p>;
  if (!detail) return <p className="border-t border-border pt-3 text-caption text-ink-faint">Loading…</p>;

  const linkedIds = new Set(detail.commitments.map((c) => c.id));
  const available = linkable.filter((c) => !linkedIds.has(c.id) && c.status !== "suggested");
  const isClosed = detail.health === "achieved" || detail.health === "abandoned";
  const hasReasoning = detail.health_reasons.length > 0 || detail.blockers.length > 0 || detail.risks.length > 0 || detail.assessment || detail.next_step;

  return (
    <div className="flex flex-col gap-4 border-t border-border pt-3">
      {!hasReasoning && (
        <p className="text-caption text-ink-faint">
          Nothing to explain yet — link a commitment below to make this goal's health measurable.
        </p>
      )}

      {detail.health_reasons.length > 0 && (
        <DetailSection label="Why">
          <ul className="flex flex-col gap-1">
            {detail.health_reasons.map((r) => (
              <li key={r} className="text-small text-ink-dim">
                · {r}
              </li>
            ))}
          </ul>
        </DetailSection>
      )}

      {(detail.blockers.length > 0 || detail.risks.length > 0) && (
        <DetailSection label="What's at risk">
          <div className="flex flex-col gap-1.5">
            {detail.blockers.map((b) => (
              <EvidenceRow key={b.id} kind={b.kind} title={b.title} detail={b.detail} tone="text-crit" />
            ))}
            {detail.risks.map((r) => (
              <div key={r.id} className="flex items-baseline justify-between gap-2">
                <EvidenceRow kind={r.kind} title={r.title} detail={r.detail} tone="text-watch" />
                {/* A person's judgement overrides Sentinel's guess, and is
                    never overwritten by a later automated pass. Only a
                    situation can be reclassified this way - a commitment's
                    risk/blocker status comes from its own due date. */}
                {r.kind === "situation" && (
                  <div className="flex flex-none gap-2">
                    <Button size="sm" variant="secondary" onClick={() => classify(r.id, "blocking")} disabled={busy}>
                      blocking
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => classify(r.id, "unrelated")} disabled={busy}>
                      not related
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </DetailSection>
      )}

      {(detail.assessment || detail.next_step) && (
        <DetailSection label="What to do next">
          {detail.assessment && <p className="text-small leading-relaxed text-ink-dim">{detail.assessment}</p>}
          {detail.next_step && <p className="mt-1 text-small leading-relaxed text-ink-dim">➡️ {detail.next_step}</p>}
        </DetailSection>
      )}

      <DetailSection label="Linked commitments">
        {detail.commitments.length === 0 ? (
          <p className="text-caption text-ink-faint">
            Nothing linked yet — link commitments to make progress measurable.
          </p>
        ) : (
          detail.commitments.map((c) => (
            <div key={c.id} className="flex items-baseline justify-between gap-2">
              <EvidenceRow kind="commitment" title={c.what} detail={c.status.replace("_", " ")} tone="text-ink-faint" />
              <div className="flex flex-none items-center gap-2 text-micro">
                <label className="flex items-center gap-1 text-ink-faint">
                  <span aria-hidden>×</span>
                  <span className="sr-only">Weight for {c.what}</span>
                  <input
                    type="number"
                    min={0.1}
                    max={100}
                    step={1}
                    defaultValue={c.weight}
                    onBlur={(e) => {
                      const next = Number(e.target.value);
                      if (next && next !== c.weight) void setWeight(c.id, next);
                    }}
                    className="w-12 rounded border border-border bg-transparent px-1 py-px text-micro text-ink-dim outline-none focus:border-border-strong"
                  />
                </label>
                <Button size="sm" variant="secondary" onClick={() => unlink(c.id)} disabled={busy}>
                  unlink
                </Button>
              </div>
            </div>
          ))
        )}
      </DetailSection>

      {/* Sentinel offering, not deciding. */}
      {detail.suggested_commitments.length > 0 && (
        <DetailSection label="Sentinel suggests linking">
          {detail.suggested_commitments.map((sg) => (
            <div key={sg.commitment_id} className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-caption text-ink-dim">{sg.what}</div>
                <div className="text-micro text-ink-faint">{sg.reason}</div>
              </div>
              <Button size="sm" variant="secondary" onClick={() => link(sg.commitment_id)} disabled={busy}>
                Link
              </Button>
            </div>
          ))}
        </DetailSection>
      )}

      {available.length > 0 && (
        <DetailSection label="Link a commitment">
          <div className="flex flex-col gap-1">
            {available.slice(0, 8).map((c) => (
              <button
                key={c.id}
                onClick={() => link(c.id)}
                disabled={busy}
                className="rounded-md px-1.5 py-1 text-left text-caption text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-50"
              >
                + {c.what}
              </button>
            ))}
          </div>
        </DetailSection>
      )}

      <div className="flex flex-wrap items-center gap-3 text-caption">
        <Button size="sm" variant="secondary" onClick={investigate} disabled={investigation.loading && investigating}>
          {investigation.loading && investigating ? "Investigating…" : "Investigate This ✨"}
        </Button>
        {isClosed ? (
          <Button size="sm" variant="secondary" onClick={() => close("reopen")} disabled={busy}>
            Reopen
          </Button>
        ) : (
          <>
            <Button size="sm" variant="secondary" onClick={() => close("achieved")} disabled={busy}>
              Achieved
            </Button>
            <Button size="sm" variant="danger" onClick={() => close("abandoned")} disabled={busy}>
              Abandon
            </Button>
          </>
        )}
      </div>

      {investigating && (investigation.investigation || investigation.error) && (
        <div>
          {investigation.error ? (
            <p className="text-caption text-crit">{investigation.error}</p>
          ) : (
            <InvestigationPanel
              investigation={investigation.investigation!}
              refreshing={investigation.refreshing}
              onRefresh={() => investigation.load(`/goals/${goalId}/investigate`, { refresh: true })}
              onClose={() => {
                setInvestigating(false);
                investigation.clear();
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}

function DetailSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="label-sub mb-1">{label}</div>
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  );
}

/** `kind` distinguishes a linked commitment from a situation at a glance -
 *  same evidence shape, different icon, so "what's at risk" never reads as
 *  one undifferentiated list. */
const KIND_ICON = { commitment: "flag", situation: "layers" } as const;

function EvidenceRow({
  kind,
  title,
  detail,
  tone,
}: {
  kind: string;
  title: string;
  detail: string;
  tone: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-caption">
      <span className="flex min-w-0 flex-1 items-center gap-1.5 truncate text-ink-dim">
        <Icon
          name={KIND_ICON[kind as keyof typeof KIND_ICON] ?? "flag"}
          size={11}
          className="flex-none text-ink-faint"
        />
        <span className="truncate">{title}</span>
      </span>
      <span className={`flex-none font-mono text-micro uppercase tracking-wide ${tone}`}>{detail}</span>
    </div>
  );
}
