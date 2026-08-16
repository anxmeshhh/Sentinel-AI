import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";

import {
  ButtonGhost,
  ButtonSecondary,
  Dot,
  InlineError,
  Panel,
  SectionLabel,
  SkeletonRows,
} from "@/components/sentinel/primitives";
import { api } from "@/lib/api";
import { serviceByKey, severityColor, severityLabel, type Severity } from "@/lib/sentinel-data";
import { ago, serviceKeyFor, useSituation } from "@/lib/sentinel-live";

export const Route = createFileRoute("/situations/$id")({
  head: () => ({ meta: [{ title: "Situation · Sentinel" }] }),
  component: SituationDetail,
});

function sev(raw: string): Severity {
  return raw === "critical" ? "critical" : raw === "reminder" ? "reminder" : "review";
}

function providerName(provider: string | null): string {
  const key = serviceKeyFor(provider);
  return (key && serviceByKey(key)?.name) || provider || "Sentinel";
}

/**
 * The page that has to answer, in order: what happened, why are these
 * connected, what is the evidence, and what should I do. Section order is
 * load-bearing - it is the argument the page is making.
 */
function SituationDetail() {
  const { id } = Route.useParams();
  const { data, isLoading, isError, refetch } = useSituation(id);
  const [acting, setActing] = useState<string | null>(null);

  async function decide(decisionId: string, verb: "confirm" | "dismiss") {
    setActing(decisionId);
    try {
      await api.post(`/decisions/${decisionId}/${verb}`);
      await refetch();
    } finally {
      setActing(null);
    }
  }

  if (isError) {
    return (
      <div>
        <BackLink />
        <InlineError message="Sentinel couldn't load this situation." onRetry={() => void refetch()} />
      </div>
    );
  }
  if (isLoading || !data) {
    return (
      <div>
        <BackLink />
        <SkeletonRows rows={6} />
      </div>
    );
  }

  const severity = sev(data.severity);
  const resolved = data.status === "resolved";

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div className="min-w-0">
        <BackLink />

        <div className="flex items-center gap-2">
          <Dot color={severityColor[severity]} />
          <span className="t-micro uppercase tracking-[0.06em]" style={{ color: severityColor[severity] }}>
            {severityLabel[severity]}
          </span>
          {resolved && (
            <span
              className="t-micro rounded-[2px] border px-1.5 py-0.5 uppercase tracking-[0.06em]"
              style={{ borderColor: "var(--good)", color: "var(--good)" }}
            >
              Resolved
            </span>
          )}
        </div>

        <h1 className={`t-h2 mt-1 font-medium ${resolved ? "text-ink-dim" : "text-ink"}`}>
          {data.entity ?? data.title}
        </h1>
        <p className="t-caption mt-1 text-ink-faint">
          {data.member_count} related findings · {data.providers.length}{" "}
          {data.providers.length === 1 ? "service" : "services"} · opened {ago(data.first_seen_at)}
          {data.occurrence_count > 1 && ` · seen ${data.occurrence_count} times`}
        </p>

        {resolved && (
          <p className="t-caption mt-3 text-ink-dim">
            Resolved {ago(data.resolved_at)}. Sentinel will tell you if it comes back.
          </p>
        )}

        {data.reasoning?.explanation && (
          <section className="mt-8">
            <SectionLabel>Why this matters</SectionLabel>
            <p className="t-body mt-2 max-w-[68ch] text-balance text-ink-dim">
              {data.reasoning.explanation}
            </p>
          </section>
        )}

        {/* The trust anchor. Deterministic, generated from the shared entity -
            never LLM prose - which is what proves the connection is a fact. */}
        <section className="mt-8">
          <SectionLabel>Why Sentinel connected these</SectionLabel>
          <p className="t-caption mt-2 text-ink-dim">{data.why_connected}</p>
        </section>

        <section className="mt-8">
          <SectionLabel>Findings ({data.findings.length})</SectionLabel>
          <ul className="mt-3 space-y-2">
            {data.findings.map((f) => (
              <li key={f.id}>
                <Panel accent={severityColor[sev(f.tier)]} className={f.live ? "" : "opacity-60"}>
                  <p className="t-micro" style={{ color: severityColor[sev(f.tier)] }}>
                    {severityLabel[sev(f.tier)]} · {providerName(f.provider)}
                    {!f.live && " · no longer active"}
                  </p>
                  <p className="t-small mt-1 text-ink">{f.title ?? "This finding has resolved"}</p>
                  {f.why && <p className="t-caption mt-0.5 text-ink-faint">{f.why}</p>}
                  {f.url && (
                    <a
                      href={f.url}
                      target="_blank"
                      rel="noreferrer"
                      className="t-caption mt-1.5 inline-block text-ink-faint underline underline-offset-2 hover:text-ink"
                    >
                      Open in {providerName(f.provider)} ↗
                    </a>
                  )}
                </Panel>
              </li>
            ))}
          </ul>
        </section>

        {data.findings.some((f) => f.occurred_at) && (
          <section className="mt-8">
            <SectionLabel>Timeline</SectionLabel>
            <ul className="mt-3 divide-y divide-border border-y border-border">
              {[...data.findings]
                .filter((f) => f.occurred_at)
                .sort((a, b) => (a.occurred_at ?? "").localeCompare(b.occurred_at ?? ""))
                .map((f) => (
                  <li key={`t-${f.id}`} className="flex gap-4 py-2">
                    <span className="t-micro w-32 shrink-0 font-mono text-ink-faint">
                      {new Date(f.occurred_at!).toLocaleString([], {
                        day: "numeric",
                        month: "short",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                    <span className="t-caption min-w-0 flex-1 truncate text-ink-dim">{f.title}</span>
                  </li>
                ))}
            </ul>
          </section>
        )}

        {data.decisions.length > 0 && (
          <section className="mt-8">
            <SectionLabel>Recommended</SectionLabel>
            <ul className="mt-3 space-y-4">
              {data.decisions.map((d) => (
                <li key={d.id}>
                  <p className="t-small text-ink">→ {d.action}</p>
                  <p className="t-caption text-ink-faint">
                    {d.memory_informed && "🧠 "}
                    {d.rationale}
                  </p>
                  <div className="mt-2 flex items-center gap-2">
                    {d.kind === "recommend" ? (
                      <>
                        <ButtonSecondary
                          disabled={acting === d.id}
                          onClick={() => void decide(d.id, "confirm")}
                        >
                          {acting === d.id ? "…" : "Confirm"}
                        </ButtonSecondary>
                        <ButtonGhost onClick={() => void decide(d.id, "dismiss")}>Dismiss</ButtonGhost>
                      </>
                    ) : (
                      <ButtonGhost onClick={() => void decide(d.id, "dismiss")}>Got it</ButtonGhost>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {data.actions.length > 0 && (
          <section className="mt-8">
            <SectionLabel>Actions taken</SectionLabel>
            <ul className="mt-3 space-y-2">
              {data.actions.map((a) => (
                <li key={a.id} className="t-caption">
                  <span className="text-ink-dim">
                    {a.status === "succeeded" ? "✓" : "•"} {a.action_type}
                  </span>{" "}
                  <span className="text-ink-faint">
                    · {ago(a.executed_at)}
                    {a.undone_at ? " · undone" : ""}
                  </span>
                  {a.verification && (
                    <p className="t-micro mt-0.5 text-ink-faint">{a.verification}</p>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <aside className="space-y-8 lg:border-l lg:border-border lg:pl-6">
        {data.entities.length > 0 && (
          <div>
            <SectionLabel>Entities</SectionLabel>
            <ul className="mt-2 space-y-1">
              {data.entities.map((e) => (
                <li key={e.id} className="t-caption text-ink-dim">
                  <span className="t-micro text-ink-faint">{e.kind}</span> {e.name}
                </li>
              ))}
            </ul>
          </div>
        )}

        {data.providers.length > 0 && (
          <div>
            <SectionLabel>Providers</SectionLabel>
            <ul className="mt-2 space-y-1">
              {data.providers.map((p) => {
                const key = serviceKeyFor(p);
                return (
                  <li key={p} className="t-caption text-ink-dim">
                    {key ? (
                      <Link to="/workspace/$service" params={{ service: key }} className="hover:text-ink">
                        {providerName(p)}
                      </Link>
                    ) : (
                      providerName(p)
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {data.memory && (
          <div>
            <SectionLabel>Memory</SectionLabel>
            <p className="t-caption mt-2 text-ink-dim">
              🧠 Seen {data.memory.observation_count} times
            </p>
            <p className="t-micro mt-1 text-ink-faint">{data.memory.summary}</p>
          </div>
        )}
      </aside>
    </div>
  );
}

function BackLink() {
  return (
    <Link to="/situations" className="t-caption mb-4 inline-block text-ink-faint hover:text-ink">
      ← Situations
    </Link>
  );
}
