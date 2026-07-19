import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { AttentionItem, CatchUp } from "../api/types";

export function attentionIcon(item: AttentionItem): string {
  if (item.origin === "manual") return "📌";
  switch (item.source_provider) {
    case "gmail":
      return "📧";
    case "google_calendar":
      return "📅";
    case "github":
      return "🔀";
    case "agent":
      return "⚠️";
    default:
      return "🔔";
  }
}

export function EvidenceLink({ item, className }: { item: AttentionItem; className: string }) {
  if (!item.evidence_url) return null;
  // Findings link inside Sentinel; everything else opens the source platform.
  if (item.evidence_url.startsWith("/")) {
    return (
      <Link to={item.evidence_url} className={className}>
        View &rarr;
      </Link>
    );
  }
  return (
    <a href={item.evidence_url} target="_blank" rel="noopener noreferrer" className={className}>
      Open &#8599;
    </a>
  );
}

/** The dashboard's "what needs my attention" strip - top 5 only, full list
 * lives in the Attention hub. Done/snooze act optimistically. */
export function AttentionStrip() {
  const [items, setItems] = useState<AttentionItem[] | null>(null);

  useEffect(() => {
    api.get<AttentionItem[]>("/attention").then(setItems).catch(() => setItems([]));
  }, []);

  async function act(item: AttentionItem, state: "done" | "snoozed") {
    setItems((list) => (list ?? []).filter((i) => i.id !== item.id));
    const body =
      state === "snoozed"
        ? { state, snoozed_until: new Date(Date.now() + 24 * 3600 * 1000).toISOString() }
        : { state };
    try {
      await api.patch(`/attention/${item.id}`, body);
    } catch {
      setItems((list) => [item, ...(list ?? [])]); // restore on failure
    }
  }

  if (items === null) return <div className="mb-6 h-16 animate-pulse rounded-md bg-surface-2" />;

  return (
    <section className="mb-8">
      <div className="mb-2.5 flex items-center justify-between">
        <h2 className="font-mono text-[11.5px] font-bold uppercase tracking-wide text-ink-dim">Needs Your Attention</h2>
        <Link to="/attention" className="font-mono text-[11px] text-accent-text hover:underline">
          View all &rarr;
        </Link>
      </div>

      {items.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-5 text-center text-[12.5px] text-ink-faint">
          Nothing needs your attention right now. ✨
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {items.slice(0, 5).map((item) => (
            <div key={item.id} className="flex items-start gap-3 rounded-md border border-border bg-surface p-3">
              <span className="mt-0.5 flex-none text-[16px]">{attentionIcon(item)}</span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-semibold text-ink">{item.title}</div>
                <div className="truncate text-[11.5px] text-ink-faint">
                  {item.why}
                  {item.origin === "detected" && <span className="ml-1.5">✨</span>}
                </div>
              </div>
              <div className="flex flex-none items-center gap-2.5 pt-0.5 font-mono text-[10.5px]">
                <button onClick={() => act(item, "done")} className="text-ink-faint underline underline-offset-2 hover:text-good">
                  Done
                </button>
                <button onClick={() => act(item, "snoozed")} title="Snooze until tomorrow" className="text-ink-faint underline underline-offset-2 hover:text-watch">
                  Snooze
                </button>
                <EvidenceLink item={item} className="font-semibold text-accent-text hover:underline" />
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** Shown only when the user has actually been away - one narrated card,
 * dismissible, never a permanent widget. */
export function CatchMeUpCard() {
  const [catchup, setCatchup] = useState<CatchUp | null>(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    api.get<CatchUp>("/attention/catchup").then(setCatchup).catch(() => setCatchup(null));
  }, []);

  if (hidden || !catchup?.narrative) return null;

  const away = catchup.gap_hours < 48 ? `${Math.round(catchup.gap_hours)} hours` : `${Math.round(catchup.gap_hours / 24)} days`;

  return (
    <section className="mb-6 rounded-md border border-accent/30 bg-accent/5 p-4">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="font-mono text-[10.5px] font-bold uppercase tracking-wide text-accent-text">
          Catch Me Up ✨ · away {away}
        </span>
        <button onClick={() => setHidden(true)} aria-label="Dismiss" className="text-[13px] text-ink-faint hover:text-ink">
          &times;
        </button>
      </div>
      <p className="text-[13px] leading-relaxed text-ink-dim">{catchup.narrative}</p>
    </section>
  );
}
