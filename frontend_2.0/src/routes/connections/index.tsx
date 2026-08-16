import { createFileRoute, Link } from "@tanstack/react-router";
import { healthMeta, services } from "@/lib/sentinel-data";
import {
  ButtonSecondary,
  Dot,
  PageHeader,
  Panel,
} from "@/components/sentinel/primitives";

export const Route = createFileRoute("/connections/")({
  head: () => ({
    meta: [
      { title: "Connections · Sentinel" },
      {
        name: "description",
        content: "The tools Sentinel reads to understand your work: Google, Microsoft 365, GitHub, Slack and Zoom.",
      },
      { property: "og:title", content: "Connections · Sentinel" },
      {
        property: "og:description",
        content: "The tools Sentinel reads to understand your work.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: ConnectionsPage,
});

const families = [
  { key: "microsoft", name: "Microsoft 365", connected: true },
  { key: "google", name: "Google", connected: true },
  { key: "github", name: "GitHub", connected: true },
  { key: "slack", name: "Slack", connected: true },
  { key: "zoom", name: "Zoom", connected: true },
  {
    key: "notion",
    name: "Notion",
    connected: false,
    blurb: "Connecting Notion lets Sentinel notice stale docs and unowned pages.",
  },
];

function ConnectionsPage() {
  return (
    <div className="max-w-[80ch]">
      <PageHeader
        title="Connections"
        caption="The tools Sentinel reads to understand your work."
      />

      <ul className="space-y-3">
        {families.map((fam) => {
          const svcs = services.filter((s) => s.familyKey === fam.key);
          const account = svcs[0]?.account;
          return (
            <Panel as="li" key={fam.key} className={fam.connected ? "" : "opacity-70"}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="t-lead text-ink">{fam.name}</h2>
                  <p className="t-caption text-ink-faint">
                    {fam.connected
                      ? `${account} · ${svcs.length} services`
                      : fam.blurb}
                  </p>
                </div>
                {fam.connected ? (
                  <span className="t-caption inline-flex items-center gap-2 text-ink-faint">
                    <Dot color="var(--good)" /> Connected
                  </span>
                ) : (
                  <ButtonSecondary>Connect</ButtonSecondary>
                )}
              </div>

              {fam.connected && (
                <>
                  <ul className="mt-4 grid gap-2 sm:grid-cols-2">
                    {svcs.map((s) => {
                      const h = healthMeta[s.health];
                      return (
                        <li key={s.key} className="t-caption flex items-center gap-2">
                          <Dot color={h.color} />
                          <Link
                            to="/workspace/$service"
                            params={{ service: s.key }}
                            className="text-ink-dim hover:text-ink"
                          >
                            {s.name}
                          </Link>
                          {s.health !== "connected" && (
                            <span className="t-micro text-ink-faint">— {h.word}</span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                  <div className="mt-4 flex justify-end">
                    <Link to="/connections/$provider" params={{ provider: fam.key }}>
                      <ButtonSecondary>Manage</ButtonSecondary>
                    </Link>
                  </div>
                </>
              )}
            </Panel>
          );
        })}
      </ul>
    </div>
  );
}
