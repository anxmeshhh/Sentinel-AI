import { createFileRoute } from "@tanstack/react-router";
import { PageHeader, SectionLabel, ButtonSecondary } from "@/components/sentinel/primitives";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings · Sentinel" },
      {
        name: "description",
        content: "Control what Sentinel watches, how it reports, and when it asks before acting.",
      },
      { property: "og:title", content: "Settings · Sentinel" },
      {
        property: "og:description",
        content: "Control what Sentinel watches and when it asks before acting.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: SettingsPage,
});

const groups = [
  {
    label: "Attention",
    rows: [
      ["Notify me about", "Critical findings only"],
      ["Quiet hours", "20:00 – 08:00"],
    ],
  },
  {
    label: "Actions",
    rows: [
      ["Ask before acting", "Always, for anything that leaves Sentinel"],
      ["High-risk actions", "Require typed confirmation"],
    ],
  },
  {
    label: "Memory",
    rows: [
      ["Remember recurring situations", "On"],
      ["Announce new memories", "Once, when first formed"],
    ],
  },
];

function SettingsPage() {
  return (
    <div className="max-w-[68ch]">
      <PageHeader title="Settings" caption="How Sentinel watches, reports and acts." />
      <div className="space-y-8">
        {groups.map((g) => (
          <section key={g.label}>
            <SectionLabel>{g.label}</SectionLabel>
            <ul className="mt-2 divide-y divide-border border-y border-border">
              {g.rows.map(([k, v]) => (
                <li key={k} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <span className="t-small text-ink">{k}</span>
                  <span className="t-caption text-ink-faint">{v}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
        <ButtonSecondary>Export what Sentinel knows</ButtonSecondary>
      </div>
    </div>
  );
}
