import { createFileRoute, Link } from "@tanstack/react-router";
import { healthMeta, services } from "@/lib/sentinel-data";
import {
  ButtonGhost,
  ButtonSecondary,
  Dot,
  SectionLabel,
} from "@/components/sentinel/primitives";

const familyNames: Record<string, string> = {
  microsoft: "Microsoft 365",
  google: "Google",
  github: "GitHub",
  slack: "Slack",
  zoom: "Zoom",
};

export const Route = createFileRoute("/connections/$provider")({
  head: ({ params }) => {
    const name = familyNames[params.provider] ?? "Connection";
    const title = `${name} connection · Sentinel`;
    const desc = `Manage what Sentinel reads from ${name}, service by service.`;
    return {
      meta: [
        { title },
        { name: "description", content: desc },
        { property: "og:title", content: title },
        { property: "og:description", content: desc },
        { property: "og:type", content: "website" },
        { name: "twitter:card", content: "summary_large_image" },
      ],
    };
  },
  component: ProviderDetail,
});

function ProviderDetail() {
  const { provider } = Route.useParams();
  const name = familyNames[provider] ?? provider;
  const svcs = services.filter((s) => s.familyKey === provider);

  return (
    <div className="max-w-[80ch]">
      <Link to="/connections" className="t-caption text-ink-faint hover:text-ink">
        ← Connections
      </Link>

      <h1 className="t-h2 mt-4 font-medium text-ink">{name}</h1>
      <p className="t-caption mt-1 text-ink-faint">
        {svcs[0]?.account ?? "Not connected"} · connected 12 Jun 2026
      </p>

      <section className="mt-8">
        <SectionLabel>Services</SectionLabel>
        <ul className="mt-2 divide-y divide-border border-y border-border">
          {svcs.map((s) => {
            const h = healthMeta[s.health];
            return (
              <li key={s.key} className="flex flex-wrap items-center gap-3 py-3">
                <Dot color={h.color} />
                <Link
                  to="/workspace/$service"
                  params={{ service: s.key }}
                  className="t-small min-w-[150px] text-ink hover:underline"
                >
                  {s.name}
                </Link>
                <span className="t-caption flex-1 text-ink-faint">
                  {h.word}
                  {s.health !== "needs_setup" && ` · synced ${s.syncedMinutesAgo}m ago`}
                </span>
                <span className="t-micro font-mono text-ink-faint">
                  {(s.name.length * 37) % 900} items
                </span>
                <ButtonGhost>Pause</ButtonGhost>
                <ButtonGhost>Disconnect</ButtonGhost>
              </li>
            );
          })}
        </ul>
      </section>

      {provider === "microsoft" && (
        <div className="mt-6 rounded-[4px] border border-dashed border-border p-4">
          <p className="t-small text-ink">🔒 Teams</p>
          <p className="t-caption mt-1 max-w-[68ch] text-ink-faint">
            Teams requires a Microsoft 365 Business or work/school account. This account
            doesn't include it, so Sentinel cannot read Teams channels.
          </p>
        </div>
      )}

      <div className="mt-8 flex gap-2">
        <ButtonSecondary>Reconnect</ButtonSecondary>
        <button className="focus-ring t-small rounded-[4px] border px-3 py-1.5" style={{ borderColor: "color-mix(in oklch, var(--crit) 50%, transparent)", color: "var(--crit)" }}>
          Disconnect {name}
        </button>
      </div>
    </div>
  );
}
