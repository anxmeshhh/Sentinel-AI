import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import {
  healthMeta,
  serviceByKey,
  services,
  workContent,
  type ServiceKey,
} from "@/lib/sentinel-data";
import {
  ButtonGhost,
  ButtonSecondary,
  Dot,
  EmptyState,
  SectionLabel,
} from "@/components/sentinel/primitives";
import { IntelligenceRail } from "@/components/sentinel/intelligence-rail";
import { Assistant } from "@/components/sentinel/assistant";
import { ActionButton } from "@/components/sentinel/action-button";

export const Route = createFileRoute("/workspace/$service")({
  head: ({ params }) => {
    const s = serviceByKey(params.service);
    const title = s ? `${s.name} · Sentinel` : "Workspace · Sentinel";
    const desc = s
      ? `Read ${s.name} and see what Sentinel noticed there, without leaving Sentinel.`
      : "A provider workspace inside Sentinel.";
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
  component: WorkspacePage,
});

function WorkspacePage() {
  const { service } = Route.useParams();
  const svc = serviceByKey(service);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  const items = useMemo(() => {
    if (!svc) return [];
    const all = workContent[svc.key as ServiceKey] ?? [];
    const q = query.trim().toLowerCase();
    return q ? all.filter((i) => (i.title + i.meta + i.body).toLowerCase().includes(q)) : all;
  }, [svc, query]);

  if (!svc) {
    return (
      <p className="t-small text-ink-dim">
        Sentinel doesn't know that service. <Link to="/connections">See connections</Link>
      </p>
    );
  }

  const health = healthMeta[svc.health];
  const current = items.find((i) => i.id === selected) ?? null;

  return (
    <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0">
        <p className="t-caption text-ink-faint">
          <Link to="/connections" className="hover:text-ink">
            {svc.family}
          </Link>{" "}
          › {svc.name}
        </p>

        <header className="mt-3 flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="grid size-11 place-items-center rounded-[4px] border border-border bg-surface-2">
              <span className="t-small text-ink-dim">{svc.name.slice(0, 2)}</span>
            </div>
            <div>
              <h1 className="t-h2 font-medium text-ink">{svc.name}</h1>
              <p className="t-caption mt-0.5 flex flex-wrap items-center gap-2 text-ink-faint">
                <Dot color={health.color} />
                <span style={{ color: health.color }}>{health.word}</span>
                <span>· {svc.account}</span>
                {svc.health !== "needs_setup" && <span>· synced {svc.syncedMinutesAgo}m ago</span>}
              </p>
            </div>
          </div>
          {svc.health !== "needs_setup" && (
            <div className="flex items-center gap-2">
              <ButtonGhost>Sync now</ButtonGhost>
              <ButtonSecondary>Quick actions</ButtonSecondary>
            </div>
          )}
        </header>

        <div className="mt-6 border-t border-rule pt-4">
          {svc.health === "needs_setup" ? (
            <EmptyState
              title={`${svc.name} isn't set up yet.`}
              body="Connecting a work or school account lets Sentinel read this service."
              action={<ButtonSecondary>Connect</ButtonSecondary>}
            />
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-1.5">
                  {["All", "Needs attention", "Recent"].map((f, i) => (
                    <button
                      key={f}
                      className="focus-ring t-caption rounded-[3px] px-2.5 py-1 transition-colors duration-150"
                      style={
                        i === 0
                          ? { background: "var(--surface-2)", color: "var(--ink)" }
                          : { color: "var(--ink-faint)" }
                      }
                    >
                      {f}
                    </button>
                  ))}
                </div>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={`Search ${svc.listLabel.toLowerCase()}…`}
                  className="focus-ring t-caption w-56 rounded-[3px] border border-border bg-surface px-2.5 py-1.5 text-ink placeholder:text-ink-faint"
                />
              </div>

              <div className="mt-4 grid gap-0 rounded-[4px] border border-border md:grid-cols-[280px_minmax(0,1fr)]">
                <div className="border-border md:border-r">
                  <SectionLabel className="px-3 pt-3">{svc.listLabel}</SectionLabel>
                  {items.length === 0 ? (
                    <p className="t-caption px-3 py-6 text-ink-faint">
                      Nothing matched that search.
                    </p>
                  ) : (
                    <ul className="mt-2 divide-y divide-border">
                      {items.map((i) => (
                        <li key={i.id}>
                          <button
                            onClick={() => setSelected(i.id)}
                            className="focus-ring w-full px-3 py-2.5 text-left transition-colors duration-150 hover:bg-surface/60"
                            style={
                              selected === i.id
                                ? { background: "color-mix(in oklch, var(--surface) 70%, transparent)" }
                                : undefined
                            }
                          >
                            <span className="t-small block truncate text-ink">{i.title}</span>
                            <span className="t-micro block truncate text-ink-faint">
                              {i.meta}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="p-4">
                  {!current ? (
                    <p className="t-caption text-ink-faint">{svc.detailEmpty}</p>
                  ) : (
                    <div className="anim-in">
                      <h2 className="t-lead text-ink">{current.title}</h2>
                      <p className="t-caption text-ink-faint">
                        {current.meta}
                        {current.sub ? ` · ${current.sub}` : ""}
                      </p>
                      {current.actions.length > 0 && (
                        <div className="my-3 flex flex-wrap gap-2 border-y border-rule py-3">
                          {current.actions.map((a) => (
                            <ActionButton
                              key={a}
                              spec={{
                                label: a,
                                preview: `${a} — ${current.title}`,
                                detail: `This runs in ${svc.name} straight away. Nobody is invited or notified.`,
                                verification: `${svc.name} confirmed the change.`,
                                undoable: !a.toLowerCase().includes("delete"),
                                highRisk: a.toLowerCase().includes("delete"),
                              }}
                            />
                          ))}
                        </div>
                      )}
                      <p className="t-body mt-3 max-w-[68ch] text-ink-dim">{current.body}</p>
                      <dl className="mt-4 divide-y divide-border border-y border-border">
                        {current.fields.map((f) => (
                          <div key={f.label} className="flex gap-4 py-2">
                            <dt className="t-micro w-28 shrink-0 text-ink-faint">{f.label}</dt>
                            <dd className="t-caption text-ink-dim">{f.value}</dd>
                          </div>
                        ))}
                      </dl>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}

          {svc.capability && (
            <div className="mt-6 rounded-[4px] border border-dashed border-border p-4">
              <p className="t-small text-ink">{svc.capability.title}</p>
              <p className="t-caption mt-1 max-w-[68ch] text-ink-faint">{svc.capability.body}</p>
            </div>
          )}
        </div>
      </div>

      <aside className="space-y-6">
        <IntelligenceRail service={svc.key} />
        <Assistant
          contextLabel={svc.family}
          placeholder={`Ask about your ${svc.listLabel.toLowerCase()}…`}
          prompts={[
            `What needs attention in ${svc.name}?`,
            "What changed since yesterday?",
            "What should I do first?",
          ]}
        />
        <div>
          <SectionLabel>Other services</SectionLabel>
          <ul className="mt-2 space-y-1">
            {services
              .filter((s) => s.familyKey === svc.familyKey && s.key !== svc.key)
              .map((s) => (
                <li key={s.key}>
                  <Link
                    to="/workspace/$service"
                    params={{ service: s.key }}
                    className="t-caption text-ink-faint hover:text-ink"
                  >
                    {s.name}
                  </Link>
                </li>
              ))}
          </ul>
        </div>
      </aside>
    </div>
  );
}
