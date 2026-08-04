import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { useWorkspace } from "../context/WorkspaceContext";

interface Announcement {
  id: string;
  summary: string;
  kind: string;
}

// "🧠 Sentinel will remember that." - the one visible sign that Sentinel is
// learning. Deliberately subtle and rare: it polls the announcements queue,
// which the server marks read on delivery, so each newly learned memory is
// shown exactly once and never again. Nothing here fires on a plain sync or an
// ordinary event - only when a genuinely new long-term memory was created.
const POLL_MS = 45_000;
const VISIBLE_MS = 7_000;

export function MemoryToast() {
  const { active } = useWorkspace();
  const [toasts, setToasts] = useState<Announcement[]>([]);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    async function poll() {
      try {
        const items = await api.get<Announcement[]>("/memory/announcements");
        if (cancelled || items.length === 0) return;
        setToasts((prev) => [...prev, ...items]);
        for (const item of items) {
          const t = window.setTimeout(() => {
            setToasts((prev) => prev.filter((x) => x.id !== item.id));
          }, VISIBLE_MS);
          timers.current.push(t);
        }
      } catch {
        // Silent: a learning notification is never worth interrupting a user for.
      }
    }

    poll();
    const interval = window.setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
      timers.current.forEach((t) => window.clearTimeout(t));
      timers.current = [];
    };
  }, [active]);

  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="pointer-events-auto flex max-w-sm items-start gap-3 rounded-md border border-border bg-surface/95 px-4 py-3 shadow-lg backdrop-blur animate-[fadeIn_0.2s_ease-out]"
        >
          <span className="text-lg leading-none" aria-hidden="true">🧠</span>
          <div className="min-w-0">
            <div className="text-small font-semibold text-ink">Sentinel will remember that</div>
            <div className="mt-0.5 truncate text-caption text-ink-faint">{t.summary}</div>
          </div>
          <button
            onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
            aria-label="Dismiss"
            className="ml-1 text-ink-faint hover:text-ink"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
