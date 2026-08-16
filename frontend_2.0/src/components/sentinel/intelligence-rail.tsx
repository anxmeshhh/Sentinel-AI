import { Link } from "@tanstack/react-router";
import {
  findingsForService,
  memories,
  serviceByKey,
  severityColor,
  situationsForService,
  type ServiceKey,
} from "@/lib/sentinel-data";
import { Dot, SectionLabel } from "./primitives";

export function IntelligenceRail({ service }: { service: ServiceKey }) {
  const svc = serviceByKey(service);
  if (!svc || svc.health === "needs_setup") return null;

  const sits = situationsForService(service);
  const finds = findingsForService(service).slice(0, 8);
  const memory = memories.find(
    (m) => !m.forgotten && sits.some((s) => s.memory && s.entity),
  );

  const quiet = sits.length === 0 && finds.length === 0;

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

      {quiet ? (
        <p className="t-caption mt-3 border-l border-border pl-3 text-ink-faint">
          Nothing needs your attention in this service right now.
        </p>
      ) : (
        <div className="mt-4 space-y-5">
          {sits.length > 0 && (
            <div>
              <SectionLabel>Situations</SectionLabel>
              <ul className="mt-2 space-y-2">
                {sits.map((s) => (
                  <li key={s.id}>
                    <Link
                      to="/situations/$id"
                      params={{ id: s.id }}
                      className="block rounded-[4px] border border-border bg-surface-2 p-3 transition-colors duration-150 hover:border-border-strong"
                      style={{ borderLeft: `2px solid ${severityColor[s.severity]}` }}
                    >
                      <p className="t-small text-ink">{s.entity}</p>
                      <p className="t-caption mt-1 line-clamp-3 text-ink-dim">{s.reasoning}</p>
                      {s.recommendations[0] && (
                        <p className="t-caption mt-2 text-ink-faint">
                          → {s.recommendations[0].text}
                        </p>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {finds.length > 0 && (
            <div>
              <SectionLabel>Findings</SectionLabel>
              <ul className="mt-2 divide-y divide-border">
                {finds.map((f) => (
                  <li key={f.id}>
                    <Link
                      to="/findings/$id"
                      params={{ id: f.id }}
                      className="flex gap-2 py-2 transition-colors duration-150 hover:bg-surface-2/60"
                    >
                      <span className="mt-[7px]">
                        <Dot color={severityColor[f.severity]} />
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

          {memory && (
            <div>
              <SectionLabel>Memory</SectionLabel>
              <Link to="/memory" className="t-caption mt-2 block text-ink-dim hover:text-ink">
                🧠 {memory.summary}
              </Link>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
