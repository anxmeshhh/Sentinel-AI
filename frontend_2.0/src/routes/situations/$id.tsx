import { createFileRoute, Link } from "@tanstack/react-router";
import {
  findingById,
  memories,
  serviceByKey,
  severityColor,
  severityLabel,
  situationById,
} from "@/lib/sentinel-data";
import {
  ButtonGhost,
  ButtonSecondary,
  Dot,
  Panel,
  Pill,
  SectionLabel,
} from "@/components/sentinel/primitives";
import { ActionButton } from "@/components/sentinel/action-button";

export const Route = createFileRoute("/situations/$id")({
  head: ({ params }) => {
    const s = situationById(params.id);
    const title = s ? `${s.entity} · Situation · Sentinel` : "Situation · Sentinel";
    const desc = s
      ? s.reasoning.slice(0, 150)
      : "Related findings Sentinel connected to the same thing.";
    return {
      meta: [
        { title },
        { name: "description", content: desc },
        { property: "og:title", content: title },
        { property: "og:description", content: desc },
        { property: "og:type", content: "article" },
        { name: "twitter:card", content: "summary_large_image" },
      ],
    };
  },
  component: SituationDetail,
});

function SituationDetail() {
  const { id } = Route.useParams();
  const s = situationById(id);
  if (!s) {
    return (
      <p className="t-small text-ink-dim">
        That situation no longer exists. <Link to="/situations">Back to situations</Link>
      </p>
    );
  }
  const findings = s.findingIds
    .map(findingById)
    .filter((f): f is NonNullable<typeof f> => Boolean(f));
  const memory = memories.find((m) => !m.forgotten && s.memory);

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_260px]">
      <div>
        <Link to="/situations" className="t-caption text-ink-faint hover:text-ink">
          ← Situations
        </Link>

        <div className="mt-4">
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-2">
              <Dot color={severityColor[s.severity]} />
              <span className="t-micro" style={{ color: severityColor[s.severity] }}>
                {severityLabel[s.severity]}
              </span>
            </span>
            {s.status === "resolved" && <Pill color="var(--good)">Resolved</Pill>}
          </div>
          <h1
            className="t-h2 mt-2 font-medium"
            style={{ color: s.status === "resolved" ? "var(--ink-dim)" : "var(--ink)" }}
          >
            {s.entity}
          </h1>
          <p className="t-caption mt-1 text-ink-faint">
            {s.findingIds.length} related findings · {s.providers.length} services · opened{" "}
            {s.openedAgo} ago
          </p>
          {s.status === "resolved" && (
            <p className="t-caption mt-2 text-ink-dim">
              Resolved {s.resolvedAgo}. Sentinel will tell you if it comes back.
            </p>
          )}
        </div>

        <section className="mt-8">
          <SectionLabel>Why this matters</SectionLabel>
          <p className="t-body mt-2 max-w-[68ch] text-ink-dim">{s.reasoning}</p>
        </section>

        <section className="mt-6">
          <SectionLabel>Why Sentinel connected these</SectionLabel>
          <p className="t-caption mt-2 text-ink-dim">{s.connectedBecause}</p>
        </section>

        <section className="mt-8">
          <SectionLabel>Findings ({findings.length})</SectionLabel>
          <ul className="mt-3 space-y-2">
            {findings.map((f) => (
              <Panel as="li" key={f.id} accent={severityColor[f.severity]}>
                <div className="t-micro flex items-center gap-2">
                  <span style={{ color: severityColor[f.severity] }}>
                    {severityLabel[f.severity]}
                  </span>
                  <span className="text-ink-faint">· {serviceByKey(f.service)?.name}</span>
                </div>
                <Link
                  to="/findings/$id"
                  params={{ id: f.id }}
                  className="t-lead mt-1 block text-ink hover:underline"
                >
                  {f.title}
                </Link>
                <p className="t-caption mt-1 text-ink-faint">{f.why}</p>
                <a
                  href={f.evidence[0]?.link}
                  target="_blank"
                  rel="noreferrer"
                  className="t-caption mt-2 inline-block text-ink-dim hover:text-ink"
                >
                  Open in {serviceByKey(f.service)?.name} ↗
                </a>
              </Panel>
            ))}
          </ul>
        </section>

        <section className="mt-8">
          <SectionLabel>Timeline</SectionLabel>
          <ul className="mt-2 divide-y divide-border border-y border-border">
            {s.timeline.map((t) => (
              <li key={t.when} className="flex gap-4 py-2">
                <span className="t-micro w-28 shrink-0 font-mono text-ink-faint">{t.when}</span>
                <span className="t-caption text-ink-dim">{t.what}</span>
              </li>
            ))}
          </ul>
        </section>

        {s.recommendations.length > 0 && (
          <section className="mt-8">
            <SectionLabel>Recommended</SectionLabel>
            <ul className="mt-3 space-y-4">
              {s.recommendations.map((r) => (
                <li key={r.id}>
                  <p className="t-small text-ink">→ {r.text}</p>
                  <p className="t-caption text-ink-faint">
                    {r.memory && "🧠 "}
                    {r.rationale}
                  </p>
                  <div className="mt-2 flex items-center gap-2">
                    <ActionButton
                      spec={{
                        label: "Confirm",
                        preview: r.text,
                        detail:
                          "Sentinel will prepare this at the provider and confirm the result.",
                        verification: "The provider confirmed the change.",
                        undoable: true,
                      }}
                    />
                    <ButtonGhost>Dismiss</ButtonGhost>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {s.actionsTaken.length > 0 && (
          <section className="mt-8">
            <SectionLabel>Actions taken</SectionLabel>
            <ul className="mt-2 divide-y divide-border border-y border-border">
              {s.actionsTaken.map((a) => (
                <li key={a.what} className="flex flex-wrap items-center gap-3 py-3">
                  <span className="t-small" style={{ color: "var(--good)" }}>
                    ✓ {a.what}
                  </span>
                  <span className="t-micro text-ink-faint">{a.when}</span>
                  <span className="t-caption flex-1 text-ink-dim">{a.verification}</span>
                  {a.undoable && <ButtonGhost>Undo</ButtonGhost>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <aside className="space-y-6 lg:border-l lg:border-border lg:pl-6">
        <div>
          <SectionLabel>Entities</SectionLabel>
          <p className="t-micro mt-2 text-ink-faint">{s.entityKind}</p>
          <p className="t-small text-ink">{s.entity}</p>
        </div>
        <div>
          <SectionLabel>Providers</SectionLabel>
          <ul className="mt-2 space-y-1">
            {s.providers.map((p) => (
              <li key={p}>
                <Link
                  to="/workspace/$service"
                  params={{ service: p }}
                  className="t-caption text-ink-dim hover:text-ink"
                >
                  {serviceByKey(p)?.name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        {memory && (
          <div>
            <SectionLabel>Memory</SectionLabel>
            <Link to="/memory" className="t-caption mt-2 block text-ink-dim hover:text-ink">
              🧠 {s.memory}
            </Link>
          </div>
        )}
        <ButtonSecondary className="w-full">Mark resolved</ButtonSecondary>
      </aside>
    </div>
  );
}
