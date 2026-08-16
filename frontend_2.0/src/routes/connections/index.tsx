import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";

import {
  ButtonSecondary,
  Dot,
  InlineError,
  PageHeader,
  Panel,
  SkeletonRows,
} from "@/components/sentinel/primitives";
import { useWorkspace } from "@/lib/auth";
import {
  FAMILIES,
  FAMILY_BLURB,
  FAMILY_LABEL,
  FAMILY_SERVICES,
  startConnect,
  type FamilyKey,
} from "@/lib/connect";
import { healthMeta, serviceByKey } from "@/lib/sentinel-data";
import { useConnections } from "@/lib/sentinel-live";

export const Route = createFileRoute("/connections/")({
  head: () => ({
    meta: [
      { title: "Connections · Sentinel" },
      {
        name: "description",
        content:
          "The tools Sentinel reads to understand your work: Google, Microsoft 365, GitHub, Slack and Zoom.",
      },
      { property: "og:title", content: "Connections · Sentinel" },
      { property: "og:description", content: "The tools Sentinel reads to understand your work." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: ConnectionsPage,
});

/**
 * Grouped by grant, not flattened into a list of twelve services: one Microsoft
 * consent produces six services, and showing them as six independent
 * connections would misrepresent what the user actually authorised.
 */
function ConnectionsPage() {
  const { data, isLoading, isError, refetch } = useConnections();
  const { active } = useWorkspace();
  const [connecting, setConnecting] = useState<FamilyKey | null>(null);
  const [error, setError] = useState<string | null>(null);

  const connections = data ?? [];

  async function connect(family: FamilyKey) {
    setConnecting(family);
    setError(null);
    try {
      await startConnect(family, "/connections");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start that connection");
      setConnecting(null);
    }
  }

  return (
    <div className="max-w-[80ch]">
      <PageHeader title="Connections" caption="The tools Sentinel reads to understand your work." />

      {active && (
        <p className="t-caption mb-4 flex items-center gap-2 text-ink-faint">
          <Dot color={active.kind === "personal" ? "var(--ctx-personal)" : "var(--ctx-org)"} />
          {active.kind === "personal"
            ? "Connected in your Personal context. Only you can see this data."
            : `Connected in ${active.name}.`}
        </p>
      )}

      {error && <InlineError message={error} />}

      {isError ? (
        <InlineError message="Sentinel couldn't load your connections." onRetry={() => void refetch()} />
      ) : isLoading ? (
        <SkeletonRows rows={4} />
      ) : (
        <ul className="space-y-3">
          {FAMILIES.map((fam) => {
            const mine = connections.filter((c) => FAMILY_SERVICES[fam].includes(c.key));
            const connected = mine.length > 0;
            const account = mine[0]?.account;
            const unhealthy = mine.filter((c) => c.health === "error" || c.health === "reconnect");

            return (
              <Panel as="li" key={fam} className={connected ? "" : "opacity-70"}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="t-lead text-ink">{FAMILY_LABEL[fam]}</h2>
                    <p className="t-caption text-ink-faint">
                      {connected
                        ? `${account} · ${mine.length} ${mine.length === 1 ? "service" : "services"}`
                        : FAMILY_BLURB[fam]}
                    </p>
                  </div>

                  {connected ? (
                    unhealthy.length > 0 ? (
                      <ButtonSecondary
                        disabled={connecting === fam}
                        onClick={() => void connect(fam)}
                      >
                        {connecting === fam ? "Opening…" : "Reconnect"}
                      </ButtonSecondary>
                    ) : (
                      <span className="t-caption inline-flex shrink-0 items-center gap-2 text-ink-faint">
                        <Dot color="var(--good)" /> Connected
                      </span>
                    )
                  ) : (
                    <ButtonSecondary disabled={connecting === fam} onClick={() => void connect(fam)}>
                      {connecting === fam ? "Opening…" : "Connect"}
                    </ButtonSecondary>
                  )}
                </div>

                {connected && (
                  <>
                    <ul className="mt-4 grid gap-2 sm:grid-cols-2">
                      {mine.map((s) => {
                        const h = healthMeta[s.health];
                        return (
                          <li key={s.key} className="t-caption flex items-center gap-2">
                            <Dot color={h.color} />
                            <Link
                              to="/workspace/$service"
                              params={{ service: s.key }}
                              className="text-ink-dim hover:text-ink"
                            >
                              {serviceByKey(s.key)?.name ?? s.name}
                            </Link>
                            {s.health !== "connected" && (
                              <span className="t-micro text-ink-faint">— {h.word}</span>
                            )}
                          </li>
                        );
                      })}
                    </ul>

                    {unhealthy.length > 0 && (
                      <p className="t-caption mt-3" style={{ color: "var(--warn)" }}>
                        {unhealthy.length === 1
                          ? `${unhealthy[0]!.name} needs reconnecting.`
                          : `${unhealthy.length} services need reconnecting.`}{" "}
                        This usually means the provider revoked access — reconnecting takes a few
                        seconds and no data is lost.
                      </p>
                    )}

                    <div className="mt-4 flex justify-end">
                      <Link to="/connections/$provider" params={{ provider: fam }}>
                        <ButtonSecondary>Manage</ButtonSecondary>
                      </Link>
                    </div>
                  </>
                )}
              </Panel>
            );
          })}
        </ul>
      )}
    </div>
  );
}
