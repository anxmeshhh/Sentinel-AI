import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { auditRows, recentActivity } from "@/lib/sentinel-data";
import {
  ButtonGhost,
  PageHeader,
  Pill,
  SectionLabel,
} from "@/components/sentinel/primitives";

export const Route = createFileRoute("/history")({
  head: () => ({
    meta: [
      { title: "History · Sentinel" },
      {
        name: "description",
        content: "Every action Sentinel ran on your behalf, with what was verified afterwards.",
      },
      { property: "og:title", content: "History · Sentinel" },
      {
        property: "og:description",
        content: "Every action Sentinel ran, and what was verified afterwards.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: HistoryPage,
});

const statusColor = {
  succeeded: "var(--good)",
  unknown: "var(--warn)",
  failed: "var(--crit)",
} as const;

function HistoryPage() {
  const [status, setStatus] = useState("All");
  const rows = auditRows.filter((r) => status === "All" || r.status === status.toLowerCase());

  return (
    <div>
      <PageHeader
        title="History"
        caption="What Sentinel has done, and what it could confirm afterwards."
      />

      <div className="mb-4 flex flex-wrap gap-1.5">
        {["All", "Succeeded", "Unknown", "Failed"].map((f) => (
          <button
            key={f}
            onClick={() => setStatus(f)}
            className="focus-ring t-caption rounded-[3px] px-2.5 py-1 transition-colors duration-150"
            style={
              status === f
                ? { background: "var(--surface-2)", color: "var(--ink)" }
                : { color: "var(--ink-faint)" }
            }
          >
            {f}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-border">
              {["Time", "Action", "Target", "Risk", "Status", "Verification", "Who", ""].map(
                (h) => (
                  <th key={h} className="label-micro px-2 py-2 text-left font-normal">
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((r) => (
              <tr key={r.id} className="align-top">
                <td className="t-micro whitespace-nowrap px-2 py-3 font-mono text-ink-faint">
                  {r.time}
                </td>
                <td className="t-caption px-2 py-3 text-ink">{r.action}</td>
                <td className="t-caption px-2 py-3 text-ink-dim">{r.target}</td>
                <td className="px-2 py-3">
                  {r.risk === "high" ? (
                    <Pill color="var(--crit)">High</Pill>
                  ) : (
                    <span className="t-micro text-ink-faint">Low</span>
                  )}
                </td>
                <td className="t-caption px-2 py-3" style={{ color: statusColor[r.status] }}>
                  {r.status}
                </td>
                <td className="t-caption max-w-[28ch] px-2 py-3 text-ink-dim">
                  {r.verification}
                </td>
                <td className="t-caption px-2 py-3 text-ink-faint">{r.who}</td>
                <td className="px-2 py-3 text-right">
                  {r.undo === "available" ? (
                    <ButtonGhost>Undo</ButtonGhost>
                  ) : (
                    <span className="t-micro text-ink-faint">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className="mt-10">
        <SectionLabel>Recent activity</SectionLabel>
        <ul className="mt-2 divide-y divide-border border-y border-border">
          {recentActivity.map((a) => (
            <li key={a.what} className="flex justify-between py-2">
              <span className="t-caption text-ink-dim">{a.what}</span>
              <span className="t-micro text-ink-faint">{a.when}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
