import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { SituationDetail } from "../api/types";
import { BackNav } from "../components/BackNav";
import { RailPanel } from "../components/assistant/CommandCenter";
import { PROVIDER_GLYPH } from "../components/ProviderIcons";
import {
  PROVIDER_LABEL,
  PROVIDER_ROUTE,
  absoluteTime,
  relativeTime,
  severityOf,
} from "../components/situations";
import {
  Action,
  ActionGroup,
  ActionLink,
  Badge,
  ButtonLink,
  EmptyState,
  Icon,
  ItemList,
  ItemRow,
  Section,
  SkeletonRows,
} from "../components/ui";

/**
 * One Situation, in the order the page has to argue it:
 *
 *   what happened -> why are these connected -> what's the evidence -> what now
 *
 * The section order is load-bearing. "Why Sentinel connected these" sits
 * directly under the prose explanation because it is the deterministic
 * sentence that makes the prose above it trustworthy - it names the shared
 * entity as a fact, not a judgement.
 *
 * Same components, tokens and spacing as the Attention page: findings are
 * ItemRows, not paragraphs in a Card, and the aside is the same RailPanel
 * shell the Situations list and Attention rails use, so the two Situations
 * surfaces read as one system.
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

      <div className="flex gap-6">
        <div className="min-w-0 flex-1">
          <header className="mb-8">
            <div className="mb-2.5 flex flex-wrap items-center gap-2">
              <Badge tone={sev.tone}>
                <Icon name={sev.icon} size={11} /> {sev.label}
              </Badge>
              {resolved && <Badge tone="good">Resolved</Badge>}
              {data.cross_provider && <Badge tone="outline">Across {data.providers.length} services</Badge>}
              {data.occurrence_count > 1 && <Badge tone="warn">Seen {data.occurrence_count} times</Badge>}
            </div>

            <h1 className={`text-h2 font-semibold tracking-tight ${resolved ? "text-ink-dim" : "text-ink"}`}>
              {data.entity ?? data.title}
            </h1>
            <p className="mt-1.5 text-caption text-ink-faint">
              {data.member_count} related finding{data.member_count === 1 ? "" : "s"} · opened{" "}
              {relativeTime(data.first_seen_at)}
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
              <p className="max-w-[68ch] text-body text-balance text-ink-dim">{data.reasoning.explanation}</p>
            </Section>
          )}

          {/* The trust anchor: deterministic, derived from the shared entity.
              Never LLM prose - that is precisely what makes it worth showing. */}
          <Section title="Why Sentinel connected these">
            <p className="max-w-[68ch] text-small text-ink-dim">{data.why_connected}</p>
          </Section>

          <Section title={`Findings (${data.findings.length})`}>
            <ItemList>
              {data.findings.map((f) => {
                const fsev = severityOf(f.tier);
                const label = f.provider ? (PROVIDER_LABEL[f.provider] ?? f.provider) : "Sentinel";
                const route = f.provider ? PROVIDER_ROUTE[f.provider] : undefined;
                return (
                  <ItemRow
                    key={f.id}
                    tone={fsev.tone}
                    title={f.title ?? "This finding has since resolved"}
                    source={label}
                    meta={[f.occurred_at ? relativeTime(f.occurred_at) : null, !f.live ? "no longer active" : null]}
                    badge={<Badge tone={fsev.tone}>{fsev.label}</Badge>}
                    details={f.why}
                    muted={!f.live}
                    actions={
                      <ActionGroup>
                        {f.url && <ActionLink kind="open" to={f.url} label={`Open in ${label}`} />}
                        {route && (
                          <ButtonLink to={route} size="sm">
                            Go to {label}
                          </ButtonLink>
                        )}
                      </ActionGroup>
                    }
                  />
                );
              })}
            </ItemList>
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
                      <span className="min-w-0 flex-1 truncate text-caption text-ink-dim">{f.title}</span>
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
              <ul className="flex flex-col gap-3">
                {data.decisions.map((d) => (
                  <li key={d.id} className="rounded-lg border border-accent/25 bg-accent/[0.05] p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-small font-medium text-ink">{d.action}</p>
                        <p className="mt-0.5 text-caption text-ink-faint">
                          {d.memory_informed && <Icon name="brain" size={11} className="mr-1 inline text-accent-text" />}
                          {d.rationale}
                        </p>
                      </div>
                      <ActionGroup>
                        {d.kind === "recommend" ? (
                          <>
                            <Action kind="confirm" loading={acting === d.id} onClick={() => void decide(d.id, "confirm")} />
                            <Action kind="dismiss" onClick={() => void decide(d.id, "dismiss")} />
                          </>
                        ) : (
                          <Action kind="dismiss" label="Got it" onClick={() => void decide(d.id, "dismiss")} />
                        )}
                      </ActionGroup>
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
                  <li key={a.id} className="flex items-start gap-2.5 py-2.5">
                    <Icon
                      name={a.status === "succeeded" ? "check" : "activity"}
                      size={13}
                      className={`mt-0.5 flex-none ${a.status === "succeeded" ? "text-good" : "text-ink-faint"}`}
                    />
                    <div className="min-w-0">
                      <p className="text-caption text-ink-dim">
                        {a.action_type}
                        <span className="text-ink-faint">
                          {" · "}
                          {relativeTime(a.executed_at)}
                          {a.undone_at ? " · undone" : ""}
                        </span>
                      </p>
                      {a.verification && <p className="mt-0.5 text-micro text-ink-faint">{a.verification}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>

        <aside className="hidden w-[268px] flex-none flex-col gap-3 self-start xl:flex">
          <div className="sticky top-0 flex flex-col gap-3">
            {data.entities.length > 0 && (
              <RailPanel title="What this concerns">
                <ul className="flex flex-col gap-1.5 px-3 pb-3">
                  {data.entities.map((e) => (
                    <li key={e.id} className="text-caption text-ink-dim">
                      <span className="text-micro text-ink-faint">{e.kind}</span> {e.name}
                    </li>
                  ))}
                </ul>
              </RailPanel>
            )}

            {data.providers.length > 0 && (
              <RailPanel title="Services involved">
                <ul className="flex flex-col gap-2 px-3 pb-3">
                  {data.providers.map((p) => {
                    const route = PROVIDER_ROUTE[p];
                    const label = PROVIDER_LABEL[p] ?? p;
                    const Glyph = PROVIDER_GLYPH[p];
                    const row = (
                      <span className="flex items-center gap-2 text-caption text-ink-dim">
                        <span className="flex h-5 w-5 flex-none items-center justify-center rounded-sm" aria-hidden="true">
                          {Glyph ? <Glyph /> : null}
                        </span>
                        {label}
                      </span>
                    );
                    return (
                      <li key={p}>
                        {route ? (
                          <Link to={route} className="block transition-colors hover:text-ink">
                            {row}
                          </Link>
                        ) : (
                          row
                        )}
                      </li>
                    );
                  })}
                </ul>
              </RailPanel>
            )}

            {data.memory && (
              <RailPanel title="Memory">
                <div className="flex gap-2.5 px-3 pb-3">
                  <span
                    className="flex h-7 w-7 flex-none items-center justify-center rounded-full bg-accent/15 text-accent-text"
                    aria-hidden="true"
                  >
                    <Icon name="brain" size={14} />
                  </span>
                  <div className="min-w-0">
                    <p className="text-caption leading-relaxed text-ink-dim">{data.memory.summary}</p>
                    <p className="mt-1 text-micro text-ink-faint">
                      Seen {data.memory.observation_count} time{data.memory.observation_count === 1 ? "" : "s"}
                    </p>
                  </div>
                </div>
              </RailPanel>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
