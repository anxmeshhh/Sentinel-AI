import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Commitment, Goal, GoalDetail } from "../api/types";
import { InvestigationPanel, useInvestigation } from "./InvestigationPanel";
import { Button } from "./ui";

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
      setGoals(await api.get<Goal[]>(`${basePath}?include_closed=true`));
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

  async function unlink(goalId: string, commitmentId: string) {
    setBusy(true);
    try {
      setDetail(await api.delete<GoalDetail>(`/goals/${goalId}/commitments/${commitmentId}`));
      await load();
    } finally {
      setBusy(false);
    }
  }

  /** How much of the goal one commitment represents. Not a task hierarchy -
   *  a way to say "the backend is most of this" without inventing sub-goals. */
  async function setWeight(goalId: string, commitmentId: string, weight: number) {
    setBusy(true);
    try {
      setDetail(await api.patch<GoalDetail>(`/goals/${goalId}/commitments/${commitmentId}`, { weight }));
      await load();
    } finally {
      setBusy(false);
    }
  }

  /** Say how a situation relates to this goal. Scope alone is not a
   *  relationship - an unclassified situation contributes nothing. */
  async function classify(goalId: string, situationId: string, relation: string) {
    setBusy(true);
    try {
      setDetail(await api.post<GoalDetail>(`/goals/${goalId}/situations`, {
        situation_id: situationId,
        relation,
      }));
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function close(goalId: string, action: "achieved" | "abandoned" | "reopen") {
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
        <Button size="sm" variant="ghost" onClick={() => setAdding((v) => !v)}>
          {adding ? "Cancel" : "+ Set a goal"}
        </Button>
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
            <Button size="sm" variant="primary" onClick={add} disabled={busy}>
              Set goal
            </Button>
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
                          <div key={r.id} className="flex items-baseline justify-between gap-2">
                            <Row title={r.title} detail={r.detail} tone="text-watch" />
                            {/* A person's judgement overrides Sentinel's guess,
                                and is never overwritten by a later pass. */}
                            {r.kind === "situation" && (
                              <div className="flex flex-none gap-2 text-micro">
                                <Button size="sm" variant="secondary" onClick={() => classify(g.id, r.id, "blocking")} disabled={busy}>
                                  blocking
                                </Button>
                                <Button size="sm" variant="ghost" onClick={() => classify(g.id, r.id, "unrelated")} disabled={busy}>
                                  not related
                                </Button>
                              </div>
                            )}
                          </div>
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
                          <div key={c.id} className="flex items-baseline justify-between gap-2">
                            <Row
                              title={c.what}
                              detail={c.status.replace("_", " ")}
                              tone="text-ink-faint"
                            />
                            <div className="flex flex-none items-center gap-2 text-micro">
                              {/* Weight: how much of the goal this represents. */}
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
                                    if (next && next !== c.weight) void setWeight(g.id, c.id, next);
                                  }}
                                  className="w-12 rounded border border-border bg-transparent px-1 py-px text-micro text-ink-dim outline-none focus:border-border-strong"
                                />
                              </label>
                              <Button size="sm" variant="secondary" onClick={() => unlink(g.id, c.id)} disabled={busy}>
                                unlink
                              </Button>
                            </div>
                          </div>
                        ))
                      )}
                    </Section>

                    {/* Sentinel offering, not deciding. */}
                    {detail.suggested_commitments.length > 0 && (
                      <Section label="Sentinel suggests linking">
                        {detail.suggested_commitments.map((sg) => (
                          <div key={sg.commitment_id} className="flex items-center justify-between gap-2">
                            <div className="min-w-0">
                              <div className="truncate text-caption text-ink-dim">{sg.what}</div>
                              <div className="text-micro text-ink-faint">{sg.reason}</div>
                            </div>
                            <Button size="sm" variant="secondary" onClick={() => link(g.id, sg.commitment_id)} disabled={busy}>
                              Link
                            </Button>
                          </div>
                        ))}
                      </Section>
                    )}

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
                      <Button size="sm" variant="secondary" onClick={() => investigateFor(g.id)} disabled={investigation.loading && investigatingId === g.id}>
                        {investigation.loading && investigatingId === g.id ? "Investigating…" : "Investigate This ✨"}
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => close(g.id, "achieved")} disabled={busy}>
                        Achieved
                      </Button>
                      <Button size="sm" variant="danger" onClick={() => close(g.id, "abandoned")} disabled={busy}>
                        Abandon
                      </Button>
                      {(g.health === "achieved" || g.health === "abandoned") && (
                        <Button size="sm" variant="secondary" onClick={() => close(g.id, "reopen")} disabled={busy}>
                          Reopen
                        </Button>
                      )}
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
