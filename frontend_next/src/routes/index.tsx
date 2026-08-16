import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "@/lib/api";
import {
  greeting,
  serviceByKey,
  severityColor,
  severityLabel,
  severityRank,
} from "@/lib/sentinel-data";
import {
  ButtonGhost,
  ButtonSecondary,
  Dot,
  EmptyState,
  InlineError,
  Panel,
  SectionLabel,
  SkeletonRows,
} from "@/components/sentinel/primitives";
import { useAuth } from "@/lib/auth";
import {
  useConnections,
  useDecisions,
  useFindings,
  useMemories,
  useSituations,
} from "@/lib/sentinel-live";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Sentinel — what needs your attention right now" },
      {
        name: "description",
        content:
          "Sentinel reads the tools you already work in and tells you what actually needs attention, why it matters, and what to do next.",
      },
      { property: "og:title", content: "Sentinel — what needs your attention right now" },
      {
        property: "og:description",
        content:
          "Findings, situations and suggested actions across Google, Microsoft 365, GitHub, Slack and Zoom.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: CommandCenter,
});

function CommandCenter() {
  const { user } = useAuth();
  const situationsQ = useSituations("open");
  const findingsQ = useFindings();
  const decisionsQ = useDecisions();
  const memoriesQ = useMemories();
  const connectionsQ = useConnections();

  const openSituations = situationsQ.data ?? [];
  const attention = (findingsQ.data ?? [])
    .filter((f) => f.status === "open")
    .sort((a, b) => severityRank[a.severity] - severityRank[b.severity]);
  const suggested = (decisionsQ.data ?? []).slice(0, 3);
  const liveMemories = (memoriesQ.data ?? []).filter((m) => !m.forgotten);
  const recentMemory = liveMemories.find((m) => m.createdHoursAgo < 24);
  const services = connectionsQ.data ?? [];

  const [acting, setActing] = useState<string | null>(null);

  /** Decisions are proposals - confirming one is a first-class act, so it goes
   *  to the server and the list is re-read rather than optimistically hidden. */
  async function act(id: string, verb: "confirm" | "dismiss") {
    setActing(id);
    try {
      await api.post(`/decisions/${id}/${verb}`);
      await decisionsQ.refetch();
    } finally {
      setActing(null);
    }
  }

  const loading = findingsQ.isLoading || situationsQ.isLoading;
  const lastSynced = services.find((s) => s.lastSynced !== "—")?.lastSynced;
  const firstName = (user?.name ?? "").split(" ")[0] || "there";

  // Recent activity is the reassurance rail: proof Sentinel is alive. Derived
  // from real connection syncs rather than a separate feed.
  const recentActivity = services
    .filter((s) => s.lastSynced !== "—")
    .slice(0, 5)
    .map((s) => ({ what: `${s.name} synced`, when: s.lastSynced }));

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0">
        <h1 className="t-h1 font-medium text-ink">
          {greeting()}, {firstName}
        </h1>
        <p className="t-caption mt-1 text-ink-dim">
          {loading
            ? "Reading your accounts…"
            : attention.length > 0
              ? `${attention.length} ${attention.length === 1 ? "thing needs" : "things need"} attention`
              : "Nothing needs your attention"}
          {lastSynced ? ` · synced ${lastSynced}` : ""}
        </p>

        {findingsQ.isError && (
          <div className="mt-4">
            <InlineError
              message="Sentinel couldn't reach the server."
              onRetry={() => void findingsQ.refetch()}
            />
          </div>
        )}

        {openSituations.length > 0 && (
          <section className="mt-8">
            <SectionLabel>Situations</SectionLabel>
            <ul className="mt-3 space-y-2">
              {openSituations.slice(0, 3).map((s) => (
                <li key={s.id}>
                  <Link to="/situations/$id" params={{ id: s.id }} className="block">
                    <Panel
                      accent={severityColor[s.severity]}
                      className="transition-colors duration-150 hover:border-border-strong"
                    >
                      <p className="t-lead font-medium text-ink">{s.entity}</p>
                      <p className="t-caption mt-0.5 text-ink-faint">
                        {s.findingIds.length} related findings ·{" "}
                        {s.providers.map((p) => serviceByKey(p)?.name).join(", ")}
                      </p>
                      <p className="t-small mt-2 line-clamp-2 text-balance text-ink-dim">
                        {s.reasoning}
                      </p>
                      {s.recommendations.slice(0, 2).map((r) => (
                        <p key={r.id} className="t-caption mt-1 text-ink-faint">
                          → {r.text}
                        </p>
                      ))}
                    </Panel>
                  </Link>
                </li>
              ))}
            </ul>
            {openSituations.length > 3 && (
              <Link to="/situations" className="t-caption mt-2 inline-block text-ink-faint hover:text-ink">
                View all {openSituations.length} situations
              </Link>
            )}
          </section>
        )}

        <section className="mt-8">
          <SectionLabel>Needs attention</SectionLabel>
          {loading ? (
            <div className="mt-3">
              <SkeletonRows rows={4} />
            </div>
          ) : attention.length === 0 ? (
            <div className="mt-3">
              <EmptyState
                title={services.length === 0 ? "Connect your first tool." : "You're clear."}
                body={
                  services.length === 0
                    ? "Sentinel reads what you already use and tells you what actually needs attention."
                    : `Sentinel is watching ${services.length} ${services.length === 1 ? "service" : "services"} and nothing needs your attention right now.`
                }
                action={
                  <Link to="/connections">
                    <ButtonSecondary>
                      {services.length === 0 ? "Connect a tool" : "Review what Sentinel is watching"}
                    </ButtonSecondary>
                  </Link>
                }
              />
            </div>
          ) : (
            <ul className="mt-3 divide-y divide-border border-y border-border">
              {attention.slice(0, 6).map((f) => (
                <li key={f.id} className="group">
                  <div className="flex items-start gap-3 py-2.5 transition-colors duration-150 hover:bg-surface/60">
                    <span className="mt-[7px]">
                      <Dot color={severityColor[f.severity]} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <Link
                        to="/findings/$id"
                        params={{ id: f.id }}
                        className="t-small block truncate text-ink"
                      >
                        <span
                          className="t-micro mr-2"
                          style={{ color: severityColor[f.severity] }}
                        >
                          {severityLabel[f.severity]}
                        </span>
                        {f.title}
                      </Link>
                      <p className="t-caption truncate text-ink-faint">{f.why}</p>
                    </div>
                    <div className="hidden shrink-0 gap-1 group-hover:flex">
                      <ButtonGhost>Snooze</ButtonGhost>
                      <ButtonGhost>Done</ButtonGhost>
                    </div>
                    <span className="t-micro shrink-0 text-ink-faint">
                      {serviceByKey(f.service)?.name}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {attention.length > 6 && (
            <Link to="/findings" className="t-caption mt-2 inline-block text-ink-faint hover:text-ink">
              View all
            </Link>
          )}
        </section>

        {suggested.length > 0 && (
          <section className="mt-8">
            <SectionLabel>Suggested</SectionLabel>
            <ul className="mt-3 space-y-4">
              {suggested.map((d) => (
                <li key={d.id}>
                  <p className="t-small text-ink">{d.text}</p>
                  <p className="t-caption text-ink-faint">
                    {d.memoryInformed && "🧠 "}
                    {d.rationale}
                  </p>
                  <div className="mt-2 flex items-center gap-2">
                    {d.kind === "recommend" ? (
                      <>
                        <ButtonSecondary
                          disabled={acting === d.id}
                          onClick={() => void act(d.id, "confirm")}
                        >
                          {acting === d.id ? "…" : "Confirm"}
                        </ButtonSecondary>
                        <ButtonGhost onClick={() => void act(d.id, "dismiss")}>Dismiss</ButtonGhost>
                      </>
                    ) : (
                      <ButtonGhost onClick={() => void act(d.id, "dismiss")}>Got it</ButtonGhost>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <aside className="space-y-8 lg:border-l lg:border-border lg:pl-6">
        <div>
          <SectionLabel>Recent activity</SectionLabel>
          <ul className="mt-2 space-y-1.5">
            {recentActivity.slice(0, 5).map((a) => (
              <li key={a.what} className="t-caption flex items-center gap-2 text-ink-dim">
                <Dot color="var(--ink-faint)" size={4} />
                <span className="flex-1 truncate">{a.what}</span>
                <span className="t-micro text-ink-faint">{a.when}</span>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <SectionLabel>Memory</SectionLabel>
          <Link to="/memory" className="t-caption mt-2 block text-ink-dim hover:text-ink">
            🧠 Sentinel remembers {liveMemories.length} things
          </Link>
          {recentMemory && (
            <p className="t-caption mt-1 text-ink-faint">{recentMemory.summary}</p>
          )}
        </div>
      </aside>
    </div>
  );
}
