import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { ctxColor, memories } from "@/lib/sentinel-data";
import {
  ButtonGhost,
  ButtonSecondary,
  Dot,
  EmptyState,
  PageHeader,
  Pill,
  SectionLabel,
} from "@/components/sentinel/primitives";

export const Route = createFileRoute("/memory")({
  head: () => ({
    meta: [
      { title: "What Sentinel remembers" },
      {
        name: "description",
        content: "Patterns Sentinel noticed by watching what keeps happening in your tools.",
      },
      { property: "og:title", content: "What Sentinel remembers" },
      {
        property: "og:description",
        content: "Patterns Sentinel noticed by watching what keeps happening.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: MemoryPage,
});

function MemoryPage() {
  const [showForgotten, setShowForgotten] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [forgotten, setForgotten] = useState<string[]>([]);

  const rows = memories.filter(
    (m) => showForgotten || (!m.forgotten && !forgotten.includes(m.id)),
  );

  return (
    <div className="max-w-[80ch]">
      <PageHeader
        title="What Sentinel remembers"
        caption="Patterns Sentinel noticed by watching what keeps happening."
        right={
          <ButtonGhost onClick={() => setShowForgotten((v) => !v)}>
            {showForgotten ? "Hide forgotten" : "Show forgotten"}
          </ButtonGhost>
        }
      />

      {rows.length === 0 ? (
        <EmptyState
          title="Sentinel hasn't noticed a pattern yet."
          body="Memories form when the same situation returns after being resolved."
        />
      ) : (
        <ul className="divide-y divide-border border-y border-border">
          {rows.map((m) => {
            const isForgotten = m.forgotten || forgotten.includes(m.id);
            return (
              <li key={m.id} className="py-5" style={{ opacity: isForgotten ? 0.6 : 1 }}>
                <div className="flex items-start justify-between gap-4">
                  <p className="t-small text-ink">{m.summary}</p>
                  {isForgotten && <Pill>Forgotten</Pill>}
                </div>

                <div className="mt-3">
                  <SectionLabel>Why Sentinel remembers this</SectionLabel>
                  <p className="t-caption mt-1 text-ink-dim">{m.why}</p>
                </div>

                {m.evidence.length > 0 && (
                  <div className="mt-3">
                    <SectionLabel>Evidence</SectionLabel>
                    <ul className="mt-1 space-y-0.5">
                      {m.evidence.map((e) => (
                        <li key={e.label}>
                          <Link
                            to="/situations/$id"
                            params={{ id: e.situationId }}
                            className="t-caption text-ink-dim hover:text-ink"
                          >
                            {e.label}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="mt-3 flex flex-wrap items-center gap-4">
                  <span className="t-micro inline-flex items-center gap-2 text-ink-faint">
                    <Dot color={ctxColor[m.scope]} />
                    {m.scopeName}
                  </span>
                  <span className="t-micro text-ink-faint">
                    First noticed {m.firstNoticed} · last seen {m.lastSeen}
                  </span>
                  {!isForgotten &&
                    (confirming === m.id ? (
                      <span className="flex items-center gap-2">
                        <span className="t-caption text-ink-dim">
                          Stop using this pattern?
                        </span>
                        <ButtonSecondary
                          onClick={() => {
                            setForgotten((f) => [...f, m.id]);
                            setConfirming(null);
                          }}
                        >
                          Forget it
                        </ButtonSecondary>
                        <ButtonGhost onClick={() => setConfirming(null)}>Cancel</ButtonGhost>
                      </span>
                    ) : (
                      <ButtonGhost onClick={() => setConfirming(m.id)}>Forget</ButtonGhost>
                    ))}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
