import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Situation } from "../api/types";
import { InvestigationPanel, useInvestigation } from "./InvestigationPanel";
import { Action, ActionGroup, Badge, ItemList, ItemRow, type Tone } from "./ui";

const STATUS_COPY: Record<string, { label: string; tone: Tone }> = {
  emerging: { label: "Emerging", tone: "warn" },
  active: { label: "Developing", tone: "crit" },
  resolved: { label: "Resolved", tone: "good" },
};

/**
 * What Sentinel noticed without being asked.
 *
 * Sits above the attention list rather than inside it, because it answers a
 * different question: attention is "what arrived", this is "what several
 * signals add up to". It renders nothing at all when nothing qualifies -
 * an empty state here would be a permanent reminder of a feature rather
 * than a signal, and this surface is only worth having if it stays quiet.
 *
 * Each situation is one compact row - what Sentinel concluded, how many
 * signals, since when. Everything Sentinel *inferred* (why it matters, the
 * suggested steps, and the raw evidence) sits behind the row's own "Why"
 * disclosure rather than printing permanently: a confidence percentage and
 * three always-visible bullet points per card was the reason this tab used
 * to read as a different, denser product than the findings list above it.
 *
 * `scope` decides which world the reader is in and is shown explicitly: a
 * person looking at a situation must know whether it was assembled from
 * their own private context or from what their team shares.
 */
export function ProactiveStrip({
  scope,
  teamId,
  alwaysShow = false,
}: {
  scope: "personal" | "channel";
  teamId?: string;
  /** On its own tab, silence is the answer rather than a reason to
   *  render nothing - a blank tab looks broken. Inline, the strip
   *  still disappears entirely when there is nothing to say. */
  alwaysShow?: boolean;
}) {
  const [situations, setSituations] = useState<Situation[]>([]);
  const [busy, setBusy] = useState(false);
  const [investigatingId, setInvestigatingId] = useState<string | null>(null);
  const investigation = useInvestigation();

  const path = scope === "channel" ? `/teams/${teamId}/proactive` : "/proactive";

  /** A situation is investigable in its own right - it already carries
   *  authorized evidence, which is all the investigation engine needs. The
   *  endpoint matches this strip's scope, so a channel situation is
   *  investigated as the channel and a private one as you. */
  function investigateFor(situationId: string) {
    if (investigatingId === situationId) {
      setInvestigatingId(null);
      investigation.clear();
      return;
    }
    setInvestigatingId(situationId);
    void investigation.load(`${path}/${situationId}/investigate`);
  }

  const load = useCallback(
    async (refresh = false) => {
      setBusy(true);
      try {
        setSituations(await api.get<Situation[]>(`${path}${refresh ? "?refresh=true" : ""}`));
      } catch {
        setSituations([]);
      } finally {
        setBusy(false);
      }
    },
    [path],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Silence is the correct output most days.
  if (situations.length === 0 && !alwaysShow) return null;

  return (
    <div className="mb-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="label-sub font-bold text-ink-dim">Sentinel noticed</span>
          <span className="rounded-full border border-border px-1.5 py-px text-micro text-ink-faint">
            {scope === "personal" ? "🔒 Private to you" : "👥 Shared with this channel"}
          </span>
        </div>
        <Action kind="retry" label="Check again" loading={busy} onClick={() => load(true)} />
      </div>

      {situations.length === 0 ? (
        <p className="text-caption text-ink-faint">
          Nothing is developing yet. Sentinel surfaces a situation here the moment several signals add up to one.
        </p>
      ) : (
        <ItemList>
          {situations.map((s) => {
            const status = STATUS_COPY[s.status] ?? STATUS_COPY.emerging;
            return (
              <ItemRow
                key={s.id}
                tone={status.tone}
                icon="layers"
                title={s.what_is_developing ?? s.title}
                meta={[
                  `${s.evidence_count} signal${s.evidence_count === 1 ? "" : "s"}`,
                  `since ${new Date(s.first_seen_at).toLocaleDateString()}`,
                ]}
                badge={<Badge tone={status.tone}>{status.label}</Badge>}
                details={
                  <div className="flex flex-col gap-2">
                    {s.why_it_matters && <p>{s.why_it_matters}</p>}
                    {s.suggested_next_steps.length > 0 && (
                      <ul className="flex flex-col gap-1">
                        {s.suggested_next_steps.map((step) => (
                          <li key={step}>→ {step}</li>
                        ))}
                      </ul>
                    )}
                    {s.evidence.length > 0 && (
                      <div className="flex flex-col gap-1 border-t border-rule pt-2">
                        <div className="text-micro uppercase tracking-wide text-ink-faint">
                          What Sentinel actually saw
                        </div>
                        {s.evidence.map((e) => (
                          <a
                            key={e.signal_id}
                            href={e.url ?? undefined}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-2 rounded-md px-1.5 py-1 text-caption text-ink-dim transition-colors hover:bg-surface-2 hover:text-ink"
                          >
                            <span className="flex-none text-micro text-ink-faint">
                              {e.occurred_at.slice(0, 10)}
                            </span>
                            <span className="min-w-0 flex-1 truncate">{e.title}</span>
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                }
                actions={
                  <ActionGroup>
                    <Action
                      kind="takeAction"
                      label="Investigate"
                      loading={investigation.loading && investigatingId === s.id}
                      onClick={() => investigateFor(s.id)}
                    />
                  </ActionGroup>
                }
              >
                {investigatingId === s.id && (investigation.investigation || investigation.error) && (
                  <div>
                    {investigation.error ? (
                      <p className="text-caption text-crit">{investigation.error}</p>
                    ) : (
                      <InvestigationPanel
                        investigation={investigation.investigation!}
                        refreshing={investigation.refreshing}
                        onRefresh={() => investigation.load(`${path}/${s.id}/investigate`, { refresh: true })}
                        onClose={() => {
                          setInvestigatingId(null);
                          investigation.clear();
                        }}
                      />
                    )}
                  </div>
                )}
              </ItemRow>
            );
          })}
        </ItemList>
      )}
    </div>
  );
}
