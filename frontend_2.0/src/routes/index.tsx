import { createFileRoute, Link } from "@tanstack/react-router";
import {
  decisions,
  findings,
  greeting,
  memories,
  recentActivity,
  serviceByKey,
  services,
  severityColor,
  severityLabel,
  severityRank,
  situations,
} from "@/lib/sentinel-data";
import {
  ButtonGhost,
  ButtonSecondary,
  Dot,
  EmptyState,
  Panel,
  SectionLabel,
} from "@/components/sentinel/primitives";

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
  const openSituations = situations.filter((s) => s.status === "open");
  const attention = findings
    .filter((f) => f.status === "open")
    .sort((a, b) => severityRank[a.severity] - severityRank[b.severity]);
  const suggested = decisions.slice(0, 3);
  const liveMemories = memories.filter((m) => !m.forgotten);
  const recentMemory = liveMemories.find((m) => m.createdHoursAgo < 24);

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0">
        <h1 className="t-h1 font-medium text-ink">{greeting()}, Animesh</h1>
        <p className="t-caption mt-1 text-ink-dim">
          {attention.length > 0
            ? `${attention.length} things need attention`
            : "Nothing needs your attention"}{" "}
          · synced 4m ago
        </p>

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
          {attention.length === 0 ? (
            <div className="mt-3">
              <EmptyState
                title="You're clear."
                body={`Sentinel is watching ${services.length} services and nothing needs your attention right now.`}
                action={<ButtonSecondary>Review what Sentinel is watching</ButtonSecondary>}
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
                        <ButtonSecondary>Confirm</ButtonSecondary>
                        <ButtonGhost>Dismiss</ButtonGhost>
                      </>
                    ) : (
                      <ButtonGhost>Got it</ButtonGhost>
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
