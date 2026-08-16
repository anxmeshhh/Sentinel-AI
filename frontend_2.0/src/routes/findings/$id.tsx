import { createFileRoute, Link } from "@tanstack/react-router";
import {
  findingById,
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

export const Route = createFileRoute("/findings/$id")({
  head: ({ params }) => {
    const f = findingById(params.id);
    const title = f ? `${f.title} · Sentinel` : "Finding · Sentinel";
    const desc = f ? f.why : "Something Sentinel thinks is worth your attention.";
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
  component: FindingDetail,
});

function FindingDetail() {
  const { id } = Route.useParams();
  const f = findingById(id);

  if (!f) {
    return (
      <p className="t-small text-ink-dim">
        That finding no longer exists. <Link to="/findings">Back to findings</Link>
      </p>
    );
  }

  const service = serviceByKey(f.service);
  const situation = f.situationId ? situationById(f.situationId) : undefined;

  return (
    <div className="max-w-[80ch]">
      <Link to="/findings" className="t-caption text-ink-faint hover:text-ink">
        ← Findings
      </Link>

      <div className="mt-4 flex items-center gap-3">
        <span className="inline-flex items-center gap-2">
          <Dot color={severityColor[f.severity]} />
          <span className="t-micro" style={{ color: severityColor[f.severity] }}>
            {severityLabel[f.severity]}
          </span>
        </span>
        <Pill
          color={
            f.status === "resolved"
              ? "var(--good)"
              : f.status === "snoozed"
                ? "var(--ink-faint)"
                : "var(--watch)"
          }
        >
          {f.status}
        </Pill>
      </div>

      <h1 className="t-h3 mt-2 font-medium text-ink">{f.title}</h1>
      <p className="t-body mt-2 text-ink-dim">{f.why}</p>

      <section className="mt-8">
        <SectionLabel>Evidence</SectionLabel>
        <ul className="mt-2 divide-y divide-border border-y border-border">
          {f.evidence.map((e) => (
            <li key={e.what} className="flex flex-wrap items-center gap-3 py-2.5">
              <span className="t-micro w-28 shrink-0 font-mono text-ink-faint">{e.when}</span>
              <span className="t-caption flex-1 text-ink-dim">{e.what}</span>
              <a
                href={e.link}
                target="_blank"
                rel="noreferrer"
                className="t-caption text-ink-faint hover:text-ink"
              >
                Open in {service?.name} ↗
              </a>
            </li>
          ))}
        </ul>
      </section>

      <div className="mt-8 grid gap-6 sm:grid-cols-2">
        <div>
          <SectionLabel>About</SectionLabel>
          <p className="t-micro mt-2 text-ink-faint">{f.entityKind}</p>
          <p className="t-small text-ink">{f.entity}</p>
        </div>
        <div>
          <SectionLabel>Source</SectionLabel>
          <p className="t-caption mt-2 text-ink-dim">
            {service?.name} · {service?.account}
          </p>
          <p className="t-micro text-ink-faint">Detected {f.history[0]?.when}</p>
        </div>
      </div>

      {situation && (
        <section className="mt-8">
          <SectionLabel>Situation</SectionLabel>
          <Panel className="mt-2" accent={severityColor[situation.severity]}>
            <Link
              to="/situations/$id"
              params={{ id: situation.id }}
              className="t-lead text-ink hover:underline"
            >
              {situation.entity}
            </Link>
            <p className="t-caption mt-1 text-ink-faint">
              Sentinel connected this with {situation.findingIds.length - 1} other findings about{" "}
              {situation.entity}.
            </p>
          </Panel>
        </section>
      )}

      <section className="mt-8">
        <SectionLabel>Actions</SectionLabel>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <ButtonSecondary>Snooze for 7 days</ButtonSecondary>
          <ButtonSecondary>Mark done</ButtonSecondary>
          <ButtonGhost>Open in {service?.name} ↗</ButtonGhost>
        </div>
      </section>

      <section className="mt-8">
        <SectionLabel>History</SectionLabel>
        <ul className="mt-2 divide-y divide-border border-y border-border">
          {f.history.map((h) => (
            <li key={h.when} className="flex gap-4 py-2">
              <span className="t-micro w-28 shrink-0 font-mono text-ink-faint">{h.when}</span>
              <span className="t-caption text-ink-dim">{h.what}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
