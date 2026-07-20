import { useState } from "react";

import { api, ApiError } from "../api/client";
import type { BriefSource, MeetingBrief } from "../api/types";

const SOURCE_ICON: Record<BriefSource["kind"], string> = {
  meeting: "📅",
  email: "📧",
  document: "📄",
  prior_meeting: "🕘",
};

const SOURCE_LABEL: Record<BriefSource["kind"], string> = {
  meeting: "Meeting",
  email: "Email",
  document: "Document",
  prior_meeting: "Previous meeting",
};

/** Shows a "Prepare Me" brief. Every claim in the narrative is backed by a
 * source listed below it, so the user can verify rather than trust. */
export function MeetingBriefPanel({
  brief,
  onRefresh,
  refreshing,
  onClose,
}: {
  brief: MeetingBrief;
  onRefresh: () => void;
  refreshing: boolean;
  onClose: () => void;
}) {
  return (
    <div className="rounded-md border border-accent/30 bg-accent/5 p-4">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-[10.5px] font-bold uppercase tracking-wide text-accent-text">
            Meeting Brief ✨
          </div>
          <div className="truncate text-[13.5px] font-semibold text-ink">{brief.title}</div>
        </div>
        <div className="flex flex-none items-center gap-2">
          <button
            onClick={onRefresh}
            disabled={refreshing}
            className="font-mono text-[10.5px] text-ink-faint underline underline-offset-2 hover:text-ink disabled:opacity-50"
          >
            {refreshing ? "Rebuilding…" : "↻ Rebuild"}
          </button>
          <button onClick={onClose} aria-label="Close" className="text-[14px] text-ink-faint hover:text-ink">
            &times;
          </button>
        </div>
      </div>

      <p className="mb-3 text-[12.5px] leading-relaxed text-ink-dim">{brief.narrative}</p>

      {brief.prep_points.length > 0 && (
        <div className="mb-3">
          <div className="mb-1 font-mono text-[10px] uppercase tracking-wide text-ink-faint">Before the meeting</div>
          <ul className="list-disc space-y-1 pl-4 text-[12px] text-ink-dim">
            {brief.prep_points.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      {brief.sources.length > 0 && (
        <div>
          <div className="mb-1 font-mono text-[10px] uppercase tracking-wide text-ink-faint">Sources</div>
          <div className="flex flex-col gap-1">
            {brief.sources.map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-[11.5px]">
                <span className="flex-none" title={SOURCE_LABEL[s.kind]}>
                  {SOURCE_ICON[s.kind]}
                </span>
                <span className="min-w-0 flex-1 truncate text-ink-dim">{s.label}</span>
                {s.url && (
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-none font-mono text-[10px] font-semibold text-accent-text hover:underline"
                  >
                    Open &#8599;
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {brief.cached && (
        <p className="mt-2.5 text-[10px] text-ink-faint">
          Generated {new Date(brief.created_at).toLocaleString()} · rebuild to refresh
        </p>
      )}
    </div>
  );
}

/** Hook holding the fetch/refresh state, so both entry points (Attention
 * hub and Meet page) share one implementation. */
export function useMeetingBrief() {
  const [brief, setBrief] = useState<MeetingBrief | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(path: string, { refresh = false } = {}) {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      setBrief(await api.post<MeetingBrief>(`${path}${refresh ? "?refresh=true" : ""}`));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't build a brief for this meeting.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  return { brief, loading, refreshing, error, load, clear: () => setBrief(null) };
}
