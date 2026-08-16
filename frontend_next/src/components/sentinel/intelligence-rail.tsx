import { Link } from "@tanstack/react-router";

import { severityColor, type ServiceKey, type Severity } from "@/lib/sentinel-data";
import { useServiceIntelligence } from "@/lib/sentinel-live";
import { Dot, SectionLabel, SkeletonRows } from "./primitives";

/**
 * What Sentinel knows about the service currently on screen.
 *
 * Provider-agnostic by construction: it renders whatever
 * /workspace/{service}/intelligence returns, and that endpoint filters the
 * canonical finding stream by which providers back the service. A new provider
 * therefore gets a rail with no code here at all.
 *
 * Scoped, never global: showing a workspace-wide feed inside a service page
 * would make the rail meaningless - the question it answers is "what does
 * Sentinel know about THIS".
 */
export function IntelligenceRail({ service }: { service: ServiceKey }) {
  const { data, isLoading, isError } = useServiceIntelligence(service);

  // A service that isn't connected has nothing to say, and an empty rail beside
  // a "connect this" page is noise.
  if (isError || (data && !data.connected)) return null;

  const situations = data?.situations ?? [];
  const findings = (data?.findings ?? []).slice(0, 8);
  const quiet = !isLoading && situations.length === 0 && findings.length === 0;

  return (
    <section className="rounded-[6px] border border-border bg-surface p-4">
      <h2 className="t-small flex items-center gap-2 font-semibold text-ink">
        <span
          aria-hidden
          className="inline-block size-[13px] rounded-full border-[2px]"
          style={{ borderColor: "var(--brand)" }}
        />
        What Sentinel sees here
      </h2>

      {isLoading ? (
        <div className="mt-4">
          <SkeletonRows rows={3} />
        </div>
      ) : quiet ? (
        <p className="t-caption mt-3 border-l border-border pl-3 text-ink-faint">
          Nothing needs your attention in this service right now.
        </p>
      ) : (
        <div className="mt-4 space-y-5">
          {situations.length > 0 && (
            <div>
              <SectionLabel>Situations</SectionLabel>
              <ul className="mt-2 space-y-2">
                {situations.map((s) => (
                  <li key={s.id}>
                    <Link
                      to="/situations/$id"
                      params={{ id: s.id }}
                      className="block rounded-[4px] border border-border bg-surface-2 p-3 transition-colors duration-150 hover:border-border-strong"
                      style={{ borderLeft: `2px solid ${severityColor[sev(s.severity)]}` }}
                    >
                      <p className="t-small text-ink">{s.title}</p>
                      {s.explanation && (
                        <p className="t-caption mt-1 line-clamp-3 text-ink-dim">{s.explanation}</p>
                      )}
                      {s.recommendations[0] && (
                        <p className="t-caption mt-2 text-ink-faint">
                          → {s.recommendations[0].action}
                        </p>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {findings.length > 0 && (
            <div>
              <SectionLabel>Findings</SectionLabel>
              <ul className="mt-2 divide-y divide-border">
                {findings.map((f) => (
                  <li key={f.id}>
                    <Link
                      to="/findings/$id"
                      params={{ id: stripSource(f.id) }}
                      className="flex gap-2 py-2 transition-colors duration-150 hover:bg-surface-2/60"
                    >
                      <span className="mt-[7px]">
                        <Dot color={severityColor[sev(f.tier)]} />
                      </span>
                      <span className="min-w-0">
                        <span className="t-caption block truncate text-ink">{f.title}</span>
                        <span className="t-micro block truncate text-ink-faint">{f.why}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function sev(raw: string): Severity {
  return raw === "critical" ? "critical" : raw === "reminder" ? "reminder" : "review";
}

/** Canonical finding ids are prefixed with their source ("attention:<uuid>"),
 *  but the detail route keys on the bare id the attention list returns. */
function stripSource(id: string): string {
  const at = id.indexOf(":");
  return at === -1 ? id : id.slice(at + 1);
}
