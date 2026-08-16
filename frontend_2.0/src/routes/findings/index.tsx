import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import {
  findings,
  serviceByKey,
  severityColor,
  severityLabel,
  severityRank,
  services,
} from "@/lib/sentinel-data";
import {
  ButtonGhost,
  Dot,
  EmptyState,
  PageHeader,
} from "@/components/sentinel/primitives";

export const Route = createFileRoute("/findings/")({
  head: () => ({
    meta: [
      { title: "Findings · Sentinel" },
      {
        name: "description",
        content: "Everything Sentinel thinks is worth your attention, across your tools.",
      },
      { property: "og:title", content: "Findings · Sentinel" },
      {
        property: "og:description",
        content: "Everything Sentinel thinks is worth your attention.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: FindingsPage,
});

function FindingsPage() {
  const [severity, setSeverity] = useState("All");
  const [status, setStatus] = useState("Open");
  const [provider, setProvider] = useState("All providers");
  const [inSituation, setInSituation] = useState(false);

  const rows = findings
    .filter((f) => (severity === "All" ? true : severityLabel[f.severity] === severity))
    .filter((f) => (status === "All" ? true : f.status === status.toLowerCase()))
    .filter((f) =>
      provider === "All providers" ? true : serviceByKey(f.service)?.name === provider,
    )
    .filter((f) => (inSituation ? Boolean(f.situationId) : true))
    .sort((a, b) => severityRank[a.severity] - severityRank[b.severity]);

  return (
    <div>
      <PageHeader
        title="Findings"
        caption="Everything Sentinel thinks is worth your attention."
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select
          value={severity}
          onChange={setSeverity}
          options={["All", "Critical", "Review", "Reminder"]}
        />
        <Select
          value={status}
          onChange={setStatus}
          options={["All", "Open", "Snoozed", "Resolved"]}
        />
        <Select
          value={provider}
          onChange={setProvider}
          options={["All providers", ...services.map((s) => s.name)]}
        />
        <button
          onClick={() => setInSituation((v) => !v)}
          className="focus-ring t-caption rounded-[3px] border px-2.5 py-1 transition-colors duration-150"
          style={{
            borderColor: inSituation ? "var(--border-strong)" : "var(--border)",
            color: inSituation ? "var(--ink)" : "var(--ink-faint)",
          }}
        >
          In a situation
        </button>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          title="Nothing needs your attention."
          body={`Sentinel is watching ${services.length} services.`}
        />
      ) : (
        <ul className="divide-y divide-border border-y border-border">
          {rows.map((f) => (
            <li key={f.id} className="group">
              <div className="flex items-start gap-3 px-1 py-3 transition-colors duration-150 hover:bg-surface/60">
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
                  {f.situationId && (
                    <Link
                      to="/situations/$id"
                      params={{ id: f.situationId }}
                      className="t-micro"
                      style={{ color: "var(--watch)" }}
                    >
                      ↳ part of a situation
                    </Link>
                  )}
                </div>
                <div className="hidden shrink-0 items-center gap-1 group-hover:flex">
                  <ButtonGhost>Snooze</ButtonGhost>
                  <ButtonGhost>Done</ButtonGhost>
                  <ButtonGhost>Open ↗</ButtonGhost>
                </div>
                <span className="t-micro shrink-0 text-ink-faint">
                  {serviceByKey(f.service)?.name} · {f.when}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="focus-ring t-caption rounded-[3px] border border-border bg-surface px-2 py-1 text-ink-dim"
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}
