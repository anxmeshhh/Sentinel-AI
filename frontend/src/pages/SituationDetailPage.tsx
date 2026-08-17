import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { SituationDetail } from "../api/types";
import { BackNav } from "../components/BackNav";
import {
  PROVIDER_LABEL,
  PROVIDER_ROUTE,
  absoluteTime,
  relativeTime,
  severityOf,
} from "../components/situations";
import { Badge, Button, Card, EmptyState, Section, SkeletonRows } from "../components/ui";

/**
 * One Situation, in the order the page has to argue it:
 *
 *   what happened → why are these connected → what's the evidence → what now
 *
 * The section order is load-bearing. "Why Sentinel connected these" sits
 * directly under the prose explanation because it is the deterministic
 * sentence that makes the prose above it trustworthy - it names the shared
 * entity as a fact, not a judgement.
 */
export function SituationDetailPage() {
  const { id = "" } = useParams();
  const [data, setData] = useState<SituationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<string | null>(null);

  function load() {
    api
      .get<SituationDetail>(`/situations/${id}`)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load this situation"));
  }

  useEffect(load, [id]);

  async function decide(decisionId: string, verb: "confirm" | "dismiss") {
    setActing(decisionId);
    try {
      await api.post(`/decisions/${decisionId}/${verb}`);
      load();
    } finally {
      setActing(null);
    }
  }

  const back = (
    <BackNav
      back={{ to: "/situations", label: "Situations" }}
      crumbs={[{ label: "Dashboard", to: "/" }, { label: "Situations", to: "/situations" }, { label: "Detail" }]}
    />
  );

  if (error) {
    return (
      <div>
        {back}
        <EmptyState title="That situation isn't available." description={error} />
      </div>
    );
  }
  if (!data) {
    return (
      <div>
        {back}
        <SkeletonRows rows={6} />
      </div>
    );
  }

  const sev = severityOf(data.severity);
  const resolved = data.status === "resolved";

  return (
    <div>
      {back}

      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_240px]">
        <div className="min-w-0">
          <header className="mb-8">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${sev.dot}`} />
              <span className={`text-micro font-semibold uppercase tracking-wide ${sev.text}`}>
                {sev.label}
              </span>
              {resolved && <Badge tone="good">Resolved</Badge>}
              {data.cross_provider && <Badge>Across {data.providers.length} services</Badge>}
              {data.occurrence_count > 1 && <Badge tone="warn">Seen {data.occurrence_count} times</Badge>}
            </div>

            <h1 className={`text-h2 font-semibold text-balance ${resolved ? "text-ink-dim" : "text-ink"}`}>
              {data.entity ?? data.title}
            </h1>
            <p className="mt-1.5 text-caption text-ink-faint">
              {data.member_count} related findings · opened {relativeTime(data.first_seen_at)}
              {data.last_activity_at && ` · last activity ${relativeTime(data.last_activity_at)}`}
            </p>

            {resolved && (
              <p className="mt-3 text-caption text-ink-dim">
                Resolved {relativeTime(data.resolved_at)}. Sentinel will tell you if it comes back.
              </p>
            )}
          </header>

          {data.reasoning?.explanation && (
            <Section title="Why this matters">
              <p className="max-w-[68ch] text-body text-balance text-ink-dim">
                {data.reasoning.explanation}
              </p>
            </Section>
          )}

          {/* The trust anchor: deterministic, derived from the shared entity.
              Never LLM prose - that is precisely what makes it worth showing. */}
          <Section title="Why Sentinel connected these">
            <p className="max-w-[68ch] text-small text-ink-dim">{data.why_connected}</p>
          </Section>

          <Section title={`Findings (${data.findings.length})`}>
            <ul className="flex flex-col gap-2.5">
              {data.findings.map((f) => {
                const fsev = severityOf(f.tier);
                const label = f.provider ? (PROVIDER_LABEL[f.provider] ?? f.provider) : "Sentinel";
                const route = f.provider ? PROVIDER_ROUTE[f.provider] : undefined;
                return (
                  <li key={f.id}>
                    <Card className={`border-l-2 ${fsev.stripe} ${f.live ? "" : "opacity-60"}`}>
                      <p className={`text-micro font-semibold uppercase tracking-wide ${fsev.text}`}>
                        {fsev.label} · {label}
                        {!f.live && " · no longer active"}
                      </p>
                      <p className="mt-1 text-small text-ink">
                        {f.title ?? "This finding has since resolved"}
                      </p>
                      {f.why && <p className="mt-0.5 text-caption text-ink-faint">{f.why}</p>}
                      <div className="mt-2 flex flex-wrap items-center gap-3">
                        {f.url && (
                          <a
                            href={f.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
                          >
                            Open in {label} ↗
                          </a>
                        )}
                        {route && (
                          <Link
                            to={route}
                            className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
                          >
                            Go to {label}
                          </Link>
                        )}
                      </div>
                    </Card>
                  </li>
                );
              })}
            </ul>
          </Section>

          {data.findings.some((f) => f.occurred_at) && (
            <Section title="Timeline" description="When each part of this actually happened.">
              <ul className="divide-y divide-border border-y border-border">
                {[...data.findings]
                  .filter((f) => f.occurred_at)
                  .sort((a, b) => (a.occurred_at ?? "").localeCompare(b.occurred_at ?? ""))
                  .map((f) => (
                    <li key={`t-${f.id}`} className="flex gap-4 py-2.5">
                      <span className="w-40 flex-none font-mono text-micro text-ink-faint">
                        {absoluteTime(f.occurred_at)}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-caption text-ink-dim">
                        {f.title}
                      </span>
                    </li>
                  ))}
              </ul>
            </Section>
          )}

          {data.decisions.length > 0 && (
            <Section
              title="Recommended"
              description="Grounded in the findings above — nothing runs until you confirm it."
            >
              <ul className="flex flex-col gap-5">
                {data.decisions.map((d) => (
                  <li key={d.id}>
                    <p className="text-small text-ink">→ {d.action}</p>
                    <p className="mt-0.5 text-caption text-ink-faint">
                      {d.memory_informed && "🧠 "}
                      {d.rationale}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {d.kind === "recommend" ? (
                        <>
                          <Button
                            size="sm"
                            disabled={acting === d.id}
                            onClick={() => void decide(d.id, "confirm")}
                          >
                            {acting === d.id ? "…" : "Confirm"}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => void decide(d.id, "dismiss")}>
                            Dismiss
                          </Button>
                        </>
                      ) : (
                        <Button size="sm" variant="ghost" onClick={() => void decide(d.id, "dismiss")}>
                          Got it
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {data.actions.length > 0 && (
            <Section title="Actions taken">
              <ul className="divide-y divide-border border-y border-border">
                {data.actions.map((a) => (
                  <li key={a.id} className="py-2.5">
                    <p className="text-caption text-ink-dim">
                      {a.status === "succeeded" ? "✓" : "•"} {a.action_type}
                      <span className="text-ink-faint">
                        {" · "}
                        {relativeTime(a.executed_at)}
                        {a.undone_at ? " · undone" : ""}
                      </span>
                    </p>
                    {a.verification && (
                      <p className="mt-0.5 text-micro text-ink-faint">{a.verification}</p>
                    )}
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>

        <aside className="flex flex-col gap-8 lg:border-l lg:border-border lg:pl-6">
          {data.entities.length > 0 && (
            <div>
              <h2 className="mb-2 text-micro font-semibold uppercase tracking-wide text-ink-faint">
                What this concerns
              </h2>
              <ul className="flex flex-col gap-1.5">
                {data.entities.map((e) => (
                  <li key={e.id} className="text-caption text-ink-dim">
                    <span className="text-micro text-ink-faint">{e.kind}</span> {e.name}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.providers.length > 0 && (
            <div>
              <h2 className="mb-2 text-micro font-semibold uppercase tracking-wide text-ink-faint">
                Services involved
              </h2>
              <ul className="flex flex-col gap-1.5">
                {data.providers.map((p) => {
                  const route = PROVIDER_ROUTE[p];
                  const label = PROVIDER_LABEL[p] ?? p;
                  return (
                    <li key={p} className="text-caption text-ink-dim">
                      {route ? (
                        <Link to={route} className="hover:text-ink">
                          {label}
                        </Link>
                      ) : (
                        label
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {data.memory && (
            <div>
              <h2 className="mb-2 text-micro font-semibold uppercase tracking-wide text-ink-faint">
                Sentinel remembers
              </h2>
              <p className="text-caption text-ink-dim">🧠 Seen {data.memory.observation_count} times</p>
              <p className="mt-1 text-micro text-ink-faint">{data.memory.summary}</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
