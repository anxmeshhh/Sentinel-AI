import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { CalendarEvent, Connection } from "../api/types";

export function CalendarPage() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [range, setRange] = useState<"upcoming" | "past">("upcoming");
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<Connection[]>("/connections").then((conns) => {
      setConnected(conns.some((c) => c.provider === "google_calendar"));
    });
  }, []);

  useEffect(() => {
    if (connected === false) {
      setLoading(false);
      return;
    }
    setLoading(true);
    api
      .get<CalendarEvent[]>(`/calendar?range=${range}&limit=30`)
      .then(setEvents)
      .catch(() => setEvents([]))
      .finally(() => setLoading(false));
  }, [range, connected]);

  if (connected === false) {
    return (
      <div className="max-w-lg rounded-md border border-dashed border-border p-10 text-center text-ink-dim">
        <p className="mb-3 text-[14px]">Google Calendar isn't connected yet.</p>
        <Link to="/settings" className="font-mono text-[13px] font-semibold text-accent-text hover:underline">
          Connect Calendar &rarr;
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      <h1 className="mb-1 text-xl font-semibold text-balance">Calendar</h1>
      <p className="mb-6 text-[13px] text-ink-dim">Title, attendees, and meeting links only.</p>

      <div className="mb-5 flex gap-1.5">
        {(["upcoming", "past"] as const).map((r) => (
          <button
            key={r}
            onClick={() => setRange(r)}
            className={`rounded-full border px-3 py-1.5 font-mono text-[11.5px] capitalize transition-colors ${
              range === r ? "border-accent bg-accent/15 text-accent-text" : "border-border text-ink-faint hover:text-ink"
            }`}
          >
            {r}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-ink-dim">Loading&hellip;</div>
      ) : events.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-8 text-center text-[13px] text-ink-faint">
          No {range} events.
        </div>
      ) : (
        <div className="rounded-md border border-border bg-surface">
          {events.map((e) => (
            <div key={e.id} className="flex items-start gap-3 border-b border-border p-3.5 last:border-b-0">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-semibold text-ink">{e.title}</div>
                <div className="mt-0.5 text-[11.5px] text-ink-faint">
                  {e.start ? new Date(e.start).toLocaleString() : "—"}
                  {e.attendee_count > 0 && ` · ${e.attendee_count} attendee${e.attendee_count === 1 ? "" : "s"}`}
                  {e.organizer && ` · ${e.organizer}`}
                </div>
              </div>
              <div className="flex flex-none items-center gap-2">
                {e.has_meeting_link && (
                  <span className="rounded-full border border-good/40 px-2 py-[3px] font-mono text-[9.5px] text-good">
                    MEET
                  </span>
                )}
                {e.url && (
                  <a
                    href={e.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[11.5px] text-ink-faint underline underline-offset-2 hover:text-ink"
                  >
                    Open
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
