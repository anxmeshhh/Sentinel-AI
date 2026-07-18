import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { CalendarEvent, Connection, Holiday, HolidayCategory } from "../api/types";
import { BackNav } from "../components/BackNav";
import { GoogleAICommand } from "../components/GoogleAICommand";

type View = "month" | "week" | "day" | "agenda";
type ScheduleTab = "ai" | "manual";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const INDIAN_STATES = [
  "Andhra Pradesh", "Assam", "Bihar", "Gujarat", "Haryana", "Karnataka", "Kerala",
  "Maharashtra", "Odisha", "Punjab", "Tamil Nadu", "Telangana", "Uttar Pradesh", "West Bengal",
];

const CATEGORY_META: Record<HolidayCategory, { label: string; dot: string; text: string; border: string }> = {
  national: { label: "National", dot: "bg-crit", text: "text-crit", border: "border-crit/40" },
  regional: { label: "Regional", dot: "bg-watch", text: "text-watch", border: "border-watch/40" },
  festival: { label: "Festival", dot: "bg-accent", text: "text-accent-text", border: "border-accent/40" },
  observance: { label: "Observance", dot: "bg-ink-faint", text: "text-ink-faint", border: "border-border" },
};

export function CalendarPage() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [view, setView] = useState<View>("agenda");
  const [anchor, setAnchor] = useState(() => new Date());
  const [agendaRange, setAgendaRange] = useState<"upcoming" | "past">("upcoming");
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [scheduleTab, setScheduleTab] = useState<ScheduleTab>("manual");

  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const [holidayState, setHolidayState] = useState("");
  const [visibleCategories, setVisibleCategories] = useState<Set<HolidayCategory>>(
    new Set(["national", "regional", "festival", "observance"])
  );

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

  useEffect(() => {
    if (!connected) return;
    const qs = new URLSearchParams({ year: String(anchor.getFullYear()) });
    if (holidayState) qs.set("state", holidayState);
    api
      .get<Holiday[]>(`/calendar/holidays?${qs.toString()}`)
      .then(setHolidays)
      .catch(() => setHolidays([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, anchor.getFullYear(), holidayState]);

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

  const visibleHolidays = useMemo(
    () => holidays.filter((h) => visibleCategories.has(h.category)),
    [holidays, visibleCategories]
  );

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

  const holidaysByDay = useMemo(() => {
    const map = new Map<string, Holiday[]>();
    for (const h of visibleHolidays) {
      const list = map.get(h.date) ?? [];
      list.push(h);
      map.set(h.date, list);
    }
    return map;
  }, [visibleHolidays]);

  function toggleCategory(cat: HolidayCategory) {
    setVisibleCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }

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
        <BackNav
          back={{ to: "/connections/google", label: "Google Workspace" }}
          crumbs={[{ label: "Dashboard", to: "/" }, { label: "Google", to: "/connections/google" }, { label: "Calendar" }]}
        />
        <p className="mb-3 text-[14px]">Google Calendar isn't connected yet.</p>
        <Link to="/settings" className="font-mono text-[13px] font-semibold text-accent-text hover:underline">
          Connect Calendar &rarr;
        </Link>
      </div>
    );
  }

  const rangeHolidays = holidaysInRange(visibleHolidays, view, agendaRange, anchor);

  return (
    <div className="max-w-3xl">
      <BackNav
        back={{ to: "/connections/google", label: "Google Workspace" }}
        crumbs={[{ label: "Dashboard", to: "/" }, { label: "Google", to: "/connections/google" }, { label: "Calendar" }]}
      />
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="mb-1 text-xl font-semibold text-balance">Calendar</h1>
          <p className="text-[13px] text-ink-dim">
            Your events, plus Indian holidays &amp; festivals from Sentinel's calendar layer — clearly separate from your own.
          </p>
        </div>
        <button
          onClick={() => setScheduleOpen((o) => !o)}
          className="flex-none rounded-md bg-accent px-3.5 py-1.5 font-mono text-[11.5px] font-bold text-ground"
        >
          {scheduleOpen ? "Close" : "+ Schedule"}
        </button>
      </div>

      {scheduleOpen && (
        <div className="mb-6 rounded-md border border-border bg-surface">
          <div className="flex gap-1.5 border-b border-border p-2.5">
            {(["manual", "ai"] as ScheduleTab[]).map((t) => (
              <button
                key={t}
                onClick={() => setScheduleTab(t)}
                className={`rounded-full border px-3 py-1.5 font-mono text-[11px] transition-colors ${
                  scheduleTab === t ? "border-accent bg-accent/15 text-accent-text" : "border-border text-ink-faint hover:text-ink"
                }`}
              >
                {t === "manual" ? "Manual" : "Ask AI"}
              </button>
            ))}
          </div>
          {scheduleTab === "manual" ? (
            <NewEventForm
              onCreated={() => {
                setScheduleOpen(false);
                void load();
              }}
            />
          ) : (
            <GoogleAICommand />
          )}
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
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

      <div className="mb-5 flex flex-wrap items-center gap-1.5">
        {(Object.keys(CATEGORY_META) as HolidayCategory[]).map((cat) => {
          const meta = CATEGORY_META[cat];
          const on = visibleCategories.has(cat);
          return (
            <button
              key={cat}
              onClick={() => toggleCategory(cat)}
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10.5px] transition-colors ${
                on ? `${meta.border} ${meta.text}` : "border-border text-ink-faint opacity-50"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
              {meta.label}
            </button>
          );
        })}
        <select
          value={holidayState}
          onChange={(e) => setHolidayState(e.target.value)}
          className="rounded-full border border-border bg-surface px-2.5 py-1 font-mono text-[10.5px] text-ink-dim outline-none focus:border-accent"
        >
          <option value="">All regional holidays</option>
          {INDIAN_STATES.map((s) => (
            <option key={s} value={s}>
              {s} only
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="text-ink-dim">Loading&hellip;</div>
      ) : view === "month" ? (
        <MonthGrid anchor={anchor} eventsByDay={eventsByDay} holidaysByDay={holidaysByDay} onSelectDay={openDay} />
      ) : (
        <AgendaList events={events} holidays={rangeHolidays} emptyLabel={view === "agenda" ? `No ${agendaRange} events.` : "No events."} />
      )}
    </div>
  );
}

function MonthGrid({
  anchor,
  eventsByDay,
  holidaysByDay,
  onSelectDay,
}: {
  anchor: Date;
  eventsByDay: Map<string, CalendarEvent[]>;
  holidaysByDay: Map<string, Holiday[]>;
  onSelectDay: (d: Date) => void;
}) {
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
          const dayHolidays = holidaysByDay.get(key) ?? [];
          const inMonth = d.getMonth() === currentMonth;
          const isToday = key === todayKey;
          return (
            <button
              key={key}
              onClick={() => onSelectDay(d)}
              className={`flex h-24 flex-col items-start gap-1 border-b border-r border-border p-1.5 text-left last:border-r-0 hover:bg-surface-2 ${
                inMonth ? "bg-surface" : "bg-ground/40"
              }`}
            >
              <span
                className={`font-mono text-[11px] ${isToday ? "flex h-5 w-5 items-center justify-center rounded-full bg-accent text-ground" : inMonth ? "text-ink-dim" : "text-ink-faint"}`}
              >
                {d.getDate()}
              </span>
              {dayHolidays.slice(0, 1).map((h) => (
                <span
                  key={h.title}
                  className={`w-full truncate rounded-full px-1.5 py-[1px] font-mono text-[9px] ${CATEGORY_META[h.category].text}`}
                >
                  &#9679; {h.title}
                </span>
              ))}
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

function AgendaList({ events, holidays, emptyLabel }: { events: CalendarEvent[]; holidays: Holiday[]; emptyLabel: string }) {
  if (events.length === 0 && holidays.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border p-8 text-center text-[13px] text-ink-faint">{emptyLabel}</div>
    );
  }
  return (
    <div className="rounded-md border border-border bg-surface">
      {holidays.map((h) => {
        const meta = CATEGORY_META[h.category];
        return (
          <div key={`${h.title}-${h.date}`} className={`flex items-center gap-3 border-b border-l-[3px] border-border ${meta.border} p-3.5 last:border-b-0`}>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate text-[13px] font-semibold text-ink">{h.title}</span>
                <span className={`flex-none rounded-full border px-2 py-[2px] font-mono text-[9px] uppercase tracking-wide ${meta.border} ${meta.text}`}>
                  {meta.label}
                </span>
              </div>
              <div className="mt-0.5 text-[11.5px] text-ink-faint">
                {new Date(h.date).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
                {h.states && ` · ${h.states.join(", ")}`}
              </div>
            </div>
            <span className="flex-none font-mono text-[10px] uppercase tracking-wide text-ink-faint">Sentinel Calendar</span>
          </div>
        );
      })}
      {events.map((e) => (
        <div key={e.id} className="flex items-start gap-3 border-b border-border p-3.5 last:border-b-0">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-[13px] font-semibold text-ink">{e.title}</span>
              {e.status === "cancelled" && (
                <span className="flex-none rounded-full border border-crit/40 px-2 py-[2px] font-mono text-[9px] uppercase text-crit">Cancelled</span>
              )}
            </div>
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
              <a href={e.url} target="_blank" rel="noopener noreferrer" className="text-[11.5px] text-ink-faint underline underline-offset-2 hover:text-ink">
                Open
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function NewEventForm({ onCreated }: { onCreated: () => void }) {
  const [title, setTitle] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [attendees, setAttendees] = useState("");
  const [createMeetLink, setCreateMeetLink] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    // Catch this before it ever reaches the backend - a round trip just to
    // learn "end must be after start" is a worse experience than an instant
    // inline message.
    if (new Date(end).getTime() <= new Date(start).getTime()) {
      setError("End time must be after start time.");
      return;
    }

    setSubmitting(true);
    try {
      await api.post("/calendar/events", {
        title,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        attendee_emails: attendees
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean),
        create_meet_link: createMeetLink,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach Sentinel to create the event - check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="p-4">
      <input
        required
        placeholder="Event title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="mb-2.5 w-full rounded-md border border-border bg-ground px-3 py-2 text-[13px] outline-none focus:border-accent"
      />
      <div className="mb-2.5 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block font-mono text-[10.5px] uppercase tracking-wide text-ink-faint">Start</span>
          <input
            required
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="w-full rounded-md border border-border bg-ground px-3 py-2 text-[13px] outline-none focus:border-accent"
          />
        </label>
        <label className="block">
          <span className="mb-1 block font-mono text-[10.5px] uppercase tracking-wide text-ink-faint">End</span>
          <input
            required
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="w-full rounded-md border border-border bg-ground px-3 py-2 text-[13px] outline-none focus:border-accent"
          />
        </label>
      </div>
      <input
        placeholder="Attendee emails, comma-separated (optional)"
        value={attendees}
        onChange={(e) => setAttendees(e.target.value)}
        className="mb-2.5 w-full rounded-md border border-border bg-ground px-3 py-2 text-[13px] outline-none focus:border-accent"
      />
      <label className="mb-3 flex items-center gap-2 text-[12.5px] text-ink-dim">
        <input type="checkbox" checked={createMeetLink} onChange={(e) => setCreateMeetLink(e.target.checked)} />
        Add a Google Meet link
      </label>
      {error && <p className="mb-2 text-[12.5px] text-crit">{error}</p>}
      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-accent px-4 py-2 font-mono text-[12.5px] font-bold text-ground disabled:opacity-50"
      >
        {submitting ? "Creating…" : "Create event"}
      </button>
    </form>
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

function holidaysInRange(holidays: Holiday[], view: View, agendaRange: "upcoming" | "past", anchor: Date): Holiday[] {
  const now = new Date();
  let start: Date, end: Date;
  if (view === "agenda") {
    if (agendaRange === "upcoming") {
      start = now;
      end = new Date(now.getFullYear() + 1, 0, 1);
    } else {
      start = new Date(now.getFullYear() - 1, 0, 1);
      end = now;
    }
  } else if (view === "week") {
    start = startOfWeek(anchor);
    end = new Date(start);
    end.setDate(end.getDate() + 7);
  } else {
    start = new Date(anchor);
    start.setHours(0, 0, 0, 0);
    end = new Date(start);
    end.setDate(end.getDate() + 1);
  }
  return holidays
    .filter((h) => {
      const d = new Date(h.date);
      return d >= start && d < end;
    })
    .sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
}
