import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { CalendarEvent, Connection } from "../api/types";

type View = "month" | "week" | "day" | "agenda";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function CalendarPage() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [view, setView] = useState<View>("agenda");
  const [anchor, setAnchor] = useState(() => new Date());
  const [agendaRange, setAgendaRange] = useState<"upcoming" | "past">("upcoming");
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
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, anchor, agendaRange, connected]);

  async function load() {
    setLoading(true);
    try {
      let data: CalendarEvent[];
      if (view === "agenda") {
        data = await api.get<CalendarEvent[]>(`/calendar?range=${agendaRange}&limit=30`);
      } else if (view === "month") {
        data = await api.get<CalendarEvent[]>(`/calendar/month?year=${anchor.getFullYear()}&month=${anchor.getMonth() + 1}`);
      } else {
        const { since, until } = view === "week" ? weekRange(anchor) : dayRange(anchor);
        data = await api.get<CalendarEvent[]>(`/calendar?since=${since}&until=${until}&limit=100`);
      }
      setEvents(data);
    } catch {
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }

  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const e of events) {
      const key = dayKey(new Date(e.start ?? e.occurred_at));
      const list = map.get(key) ?? [];
      list.push(e);
      map.set(key, list);
    }
    return map;
  }, [events]);

  function openDay(d: Date) {
    setAnchor(d);
    setView("day");
  }

  function stepAnchor(delta: number) {
    const next = new Date(anchor);
    if (view === "month") next.setMonth(next.getMonth() + delta);
    else if (view === "week") next.setDate(next.getDate() + delta * 7);
    else next.setDate(next.getDate() + delta);
    setAnchor(next);
  }

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

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1.5">
          {(["month", "week", "day", "agenda"] as View[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`rounded-full border px-3 py-1.5 font-mono text-[11.5px] capitalize transition-colors ${
                view === v ? "border-accent bg-accent/15 text-accent-text" : "border-border text-ink-faint hover:text-ink"
              }`}
            >
              {v}
            </button>
          ))}
        </div>

        {view === "agenda" ? (
          <div className="flex gap-1.5">
            {(["upcoming", "past"] as const).map((r) => (
              <button
                key={r}
                onClick={() => setAgendaRange(r)}
                className={`rounded-full border px-3 py-1.5 font-mono text-[11.5px] capitalize transition-colors ${
                  agendaRange === r ? "border-accent bg-accent/15 text-accent-text" : "border-border text-ink-faint hover:text-ink"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button onClick={() => stepAnchor(-1)} className="rounded-md border border-border px-2.5 py-1 text-[12px] text-ink-dim hover:border-accent">
              &larr;
            </button>
            <span className="min-w-[8rem] text-center font-mono text-[12px] text-ink-dim">{anchorLabel(view, anchor)}</span>
            <button onClick={() => stepAnchor(1)} className="rounded-md border border-border px-2.5 py-1 text-[12px] text-ink-dim hover:border-accent">
              &rarr;
            </button>
            <button onClick={() => setAnchor(new Date())} className="ml-1 font-mono text-[11px] text-ink-faint underline underline-offset-2 hover:text-ink">
              Today
            </button>
          </div>
        )}
      </div>

      {loading ? (
        <div className="text-ink-dim">Loading&hellip;</div>
      ) : view === "month" ? (
        <MonthGrid anchor={anchor} eventsByDay={eventsByDay} onSelectDay={openDay} />
      ) : (
        <AgendaList events={events} emptyLabel={view === "agenda" ? `No ${agendaRange} events.` : "No events."} />
      )}
    </div>
  );
}

function MonthGrid({ anchor, eventsByDay, onSelectDay }: { anchor: Date; eventsByDay: Map<string, CalendarEvent[]>; onSelectDay: (d: Date) => void }) {
  const days = buildMonthGrid(anchor);
  const currentMonth = anchor.getMonth();
  const todayKey = dayKey(new Date());

  return (
    <div className="overflow-hidden rounded-md border border-border">
      <div className="grid grid-cols-7 border-b border-border bg-surface">
        {WEEKDAY_LABELS.map((w) => (
          <div key={w} className="p-2 text-center font-mono text-[10.5px] uppercase tracking-wide text-ink-faint">
            {w}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {days.map((d) => {
          const key = dayKey(d);
          const dayEvents = eventsByDay.get(key) ?? [];
          const inMonth = d.getMonth() === currentMonth;
          const isToday = key === todayKey;
          return (
            <button
              key={key}
              onClick={() => onSelectDay(d)}
              className={`flex h-20 flex-col items-start gap-1 border-b border-r border-border p-1.5 text-left last:border-r-0 hover:bg-surface-2 ${
                inMonth ? "bg-surface" : "bg-ground/40"
              }`}
            >
              <span
                className={`font-mono text-[11px] ${isToday ? "flex h-5 w-5 items-center justify-center rounded-full bg-accent text-ground" : inMonth ? "text-ink-dim" : "text-ink-faint"}`}
              >
                {d.getDate()}
              </span>
              {dayEvents.length > 0 && (
                <span className="truncate rounded-full bg-accent/15 px-1.5 py-[1px] font-mono text-[9.5px] text-accent-text">
                  {dayEvents.length} event{dayEvents.length === 1 ? "" : "s"}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function AgendaList({ events, emptyLabel }: { events: CalendarEvent[]; emptyLabel: string }) {
  if (events.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-8 text-center text-[13px] text-ink-faint">{emptyLabel}</div>
    );
  }
  return (
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
              <span className="rounded-full border border-good/40 px-2 py-[3px] font-mono text-[9.5px] text-good">MEET</span>
            )}
            {e.url && (
              <a href={e.url} target="_blank" rel="noreferrer" className="text-[11.5px] text-ink-faint underline underline-offset-2 hover:text-ink">
                Open
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function dayKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function buildMonthGrid(anchor: Date): Date[] {
  const year = anchor.getFullYear();
  const month = anchor.getMonth();
  const firstOfMonth = new Date(year, month, 1);
  const gridStart = new Date(year, month, 1 - firstOfMonth.getDay());
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    return d;
  });
}

function startOfWeek(d: Date): Date {
  const copy = new Date(d);
  copy.setHours(0, 0, 0, 0);
  copy.setDate(copy.getDate() - copy.getDay());
  return copy;
}

function weekRange(anchor: Date): { since: string; until: string } {
  const start = startOfWeek(anchor);
  const end = new Date(start);
  end.setDate(end.getDate() + 7);
  return { since: start.toISOString(), until: end.toISOString() };
}

function dayRange(anchor: Date): { since: string; until: string } {
  const start = new Date(anchor);
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { since: start.toISOString(), until: end.toISOString() };
}

function anchorLabel(view: View, anchor: Date): string {
  if (view === "month") return anchor.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  if (view === "day") return anchor.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const start = startOfWeek(anchor);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  return `${start.toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${end.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}
