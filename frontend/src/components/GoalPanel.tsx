import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Commitment, Goal, GoalDetail } from "../api/types";
import { InvestigationPanel, useInvestigation } from "./InvestigationPanel";

const HEALTH_COPY: Record<string, { label: string; tone: string; border: string }> = {
  blocked: { label: "Blocked", tone: "text-crit", border: "border-crit/40 bg-crit/5" },
  at_risk: { label: "At risk", tone: "text-crit", border: "border-crit/30 bg-crit/[0.04]" },
  on_track: { label: "On track", tone: "text-good", border: "border-good/30 bg-good/[0.04]" },
  unknown: { label: "Not yet measurable", tone: "text-ink-faint", border: "border-border bg-surface" },
  achieved: { label: "Achieved", tone: "text-good", border: "border-border bg-surface" },
  abandoned: { label: "Abandoned", tone: "text-ink-faint", border: "border-border bg-surface" },
};

/**
 * Goal Intelligence.
 *
 * Answers five questions and nothing else: what are we trying to achieve,
 * how are we doing, what is blocking us, what is at risk, and what next.
 * Deliberately not a project board - no columns, no sprints, no dependency
 * graph.
 *
 * The health badge is always accompanied by the reasons that produced it,
 * because a user must be able to see *why* Sentinel called a goal blocked
 * rather than take the label on faith. Progress is only ever shown when it
 * is measurable; when nothing is linked the panel says so instead of
 * displaying a confident 0%.
 */
export function GoalPanel({ scope, teamId }: { scope: "personal" | "channel"; teamId?: string }) {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [detail, setDetail] = useState<GoalDetail | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [outcome, setOutcome] = useState("");
  const [due, setDue] = useState("");
  const [linkable, setLinkable] = useState<Commitment[]>([]);
  const investigation = useInvestigation();
  const [investigatingId, setInvestigatingId] = useState<string | null>(null);

  const basePath = scope === "channel" ? `/teams/${teamId}/goals` : "/goals";
  const commitmentsPath = scope === "channel" ? `/teams/${teamId}/commitments` : "/commitments";

  const load = useCallback(async () => {
    try {
      setGoals(await api.get<Goal[]>(basePath));
    } catch {
      setGoals([]);
    }
  }, [basePath]);

  useEffect(() => {
    void load();
  }, [load]);

  async function open(id: string) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(id);
    setBusy(true);
    try {
      const [d, c] = await Promise.all([
        api.get<GoalDetail>(`/goals/${id}?refresh=true`),
        api.get<Commitment[]>(commitmentsPath),
      ]);
      setDetail(d);
      setLinkable(c);
    } finally {
      setBusy(false);
    }
  }

  async function add() {
    if (title.trim().length < 2) return;
    setBusy(true);
    try {
      await api.post(basePath, {
        title: title.trim(),
        outcome: outcome.trim() || null,
        due_at: due ? new Date(due).toISOString() : null,
      });
      setTitle("");
      setOutcome("");
      setDue("");
      setAdding(false);
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function link(goalId: string, commitmentId: string) {
    setBusy(true);
    try {
      setDetail(await api.post<GoalDetail>(`/goals/${goalId}/commitments`, { commitment_id: commitmentId }));
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function close(goalId: string, action: "achieved" | "abandoned") {
    setBusy(true);
    try {
      await api.post(`/goals/${goalId}/${action}`);
      setOpenId(null);
      setDetail(null);
      await load();
    } finally {
      setBusy(false);
    }
  }

  function investigateFor(goalId: string) {
    if (investigatingId === goalId) {
      setInvestigatingId(null);
      investigation.clear();
      return;
    }
    setInvestigatingId(goalId);
    void investigation.load(`/goals/${goalId}/investigate`);
  }

  const linkedIds = new Set(detail?.commitments.map((c) => c.id) ?? []);
  const available = linkable.filter((c) => !linkedIds.has(c.id) && c.status !== "suggested");

  return (
    <div className="mb-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="label-sub font-bold text-ink-dim">🎯 Goals</span>
          <span className="rounded-full border border-border px-1.5 py-px text-micro text-ink-faint">
            {scope === "personal" ? "🔒 Private to you" : "👥 Shared with this channel"}
          </span>
        </div>
        <button
          onClick={() => setAdding((v) => !v)}
          className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
        >
          {adding ? "Cancel" : "+ Set a goal"}
        </button>
      </div>

      {adding && (
        <div className="mb-2 flex flex-col gap-2 rounded-md border border-border bg-surface p-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={scope === "personal" ? "Prepare for my interview" : "Launch Product V2"}
            className="rounded-md border border-border bg-transparent px-2 py-1.5 text-small outline-none focus:border-border-strong"
          />
          <input
            value={outcome}
            onChange={(e) => setOutcome(e.target.value)}
            placeholder="What does done look like?"
            className="rounded-md border border-border bg-transparent px-2 py-1.5 text-caption outline-none focus:border-border-strong"
          />
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={due}
              onChange={(e) => setDue(e.target.value)}
              className="rounded-md border border-border bg-transparent px-2 py-1.5 text-caption text-ink-dim outline-none focus:border-border-strong"
            />
            <button onClick={add} disabled={busy} className="btn-primary">
              Set goal
            </button>
          </div>
        </div>
      )}

      {goals.length === 0 ? (
        <p className="text-caption text-ink-faint">No goals set{scope === "channel" ? " for this channel" : ""}.</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {goals.map((g) => {
            const health = HEALTH_COPY[g.health] ?? HEALTH_COPY.unknown;
            const isOpen = openId === g.id;
            return (
              <div key={g.id} className={`rounded-md border p-3 ${health.border}`}>
                <button onClick={() => open(g.id)} className="flex w-full items-start justify-between gap-3 text-left">
                  <div className="min-w-0">
                    <div className="text-small font-semibold text-ink">{g.title}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-micro text-ink-faint">
                      <span className={`font-mono uppercase tracking-wide ${health.tone}`}>{health.label}</span>
                      {/* Only shown when it means something. */}
                      {g.progress !== null && <span>· {Math.round(g.progress * 100)}% done</span>}
                      {g.due_at && <span>· by {new Date(g.due_at).toLocaleDateString()}</span>}
                    </div>
                  </div>
                  <span className="flex-none text-micro text-ink-faint">{isOpen ? "hide" : "open"}</span>
                </button>

                {/* Why Sentinel says what it says - always, not on request. */}
                {g.health_reasons.length > 0 && (
                  <ul className="mt-1.5 flex flex-col gap-0.5">
                    {g.health_reasons.map((r) => (
                      <li key={r} className="text-caption text-ink-dim">
                        · {r}
                      </li>
                    ))}
                  </ul>
                )}

                {g.assessment && <p className="mt-2 text-small leading-relaxed text-ink-dim">{g.assessment}</p>}
                {g.next_step && (
                  <p className="mt-1 text-small leading-relaxed text-ink-dim">➡️ {g.next_step}</p>
                )}

                {isOpen && detail && detail.id === g.id && (
                  <div className="mt-3 flex flex-col gap-3 border-t border-border pt-3">
                    {detail.blockers.length > 0 && (
                      <Section label="🚧 Blocking this">
                        {detail.blockers.map((b) => (
                          <Row key={b.id} title={b.title} detail={b.detail} tone="text-crit" />
                        ))}
                      </Section>
                    )}

                    {detail.risks.length > 0 && (
                      <Section label="⚠️ Risks in this context">
                        {detail.risks.map((r) => (
                          <Row key={r.id} title={r.title} detail={r.detail} tone="text-watch" />
                        ))}
                      </Section>
                    )}

                    <Section label="Linked commitments">
                      {detail.commitments.length === 0 ? (
                        <p className="text-caption text-ink-faint">
                          Nothing linked yet — link commitments to make progress measurable.
                        </p>
                      ) : (
                        detail.commitments.map((c) => (
                          <Row key={c.id} title={c.what} detail={c.status.replace("_", " ")} tone="text-ink-faint" />
                        ))
                      )}
                    </Section>

                    {available.length > 0 && (
                      <Section label="Link a commitment">
                        <div className="flex flex-col gap-1">
                          {available.slice(0, 8).map((c) => (
                            <button
                              key={c.id}
                              onClick={() => link(g.id, c.id)}
                              disabled={busy}
                              className="rounded-md px-1.5 py-1 text-left text-caption text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-50"
                            >
                              + {c.what}
                            </button>
                          ))}
                        </div>
                      </Section>
                    )}

                    <div className="flex flex-wrap items-center gap-3 text-caption">
                      <button
                        onClick={() => investigateFor(g.id)}
                        disabled={investigation.loading && investigatingId === g.id}
                        className={`underline underline-offset-2 disabled:opacity-50 ${
                          investigatingId === g.id ? "text-accent-text" : "text-ink-faint hover:text-ink"
                        }`}
                      >
                        {investigation.loading && investigatingId === g.id ? "Investigating…" : "Investigate This ✨"}
                      </button>
                      <button
                        onClick={() => close(g.id, "achieved")}
                        disabled={busy}
                        className="text-ink-faint underline underline-offset-2 hover:text-good disabled:opacity-50"
                      >
                        Achieved
                      </button>
                      <button
                        onClick={() => close(g.id, "abandoned")}
                        disabled={busy}
                        className="text-ink-faint underline underline-offset-2 hover:text-crit disabled:opacity-50"
                      >
                        Abandon
                      </button>
                    </div>

                    {investigatingId === g.id && (investigation.investigation || investigation.error) && (
                      <div>
                        {investigation.error ? (
                          <p className="text-caption text-crit">{investigation.error}</p>
                        ) : (
                          <InvestigationPanel
                            investigation={investigation.investigation!}
                            refreshing={investigation.refreshing}
                            onRefresh={() => investigation.load(`/goals/${g.id}/investigate`, { refresh: true })}
                            onClose={() => {
                              setInvestigatingId(null);
                              investigation.clear();
                            }}
                          />
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="label-sub mb-1">{label}</div>
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  );
}

function Row({ title, detail, tone }: { title: string; detail: string; tone: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-caption">
      <span className="min-w-0 flex-1 truncate text-ink-dim">{title}</span>
      <span className={`flex-none font-mono text-micro uppercase tracking-wide ${tone}`}>{detail}</span>
    </div>
  );
}
