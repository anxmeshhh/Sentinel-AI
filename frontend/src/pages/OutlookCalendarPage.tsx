import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { OutlookCalendar, OutlookEvent } from "../api/types";
import { CalendarIcon } from "../components/ProviderIcons";
import { MICROSOFT_ASSISTANT } from "../components/workspace/assistantConfigs";
import { ActionButton, ProviderWorkspace } from "../components/workspace/ProviderWorkspace";
import { Button, Icon, LoadingBlock } from "../components/ui";

/**
 * Outlook Calendar as a workspace: see the real agenda, and create, edit or
 * cancel meetings without leaving Sentinel.
 *
 * Second page on the shared shell, and the point of the shell - this file is
 * only the work surface. Header, health, intelligence rail, assistant and the
 * whole confirm/execute/verify/audit/undo flow come from ProviderWorkspace and
 * ActionButton, unchanged from Outlook Mail.
 */
export function OutlookCalendarPage() {
  const [data, setData] = useState<OutlookCalendar | null>(null);
  const [loading, setLoading] = useState(true);
  const [notConnected, setNotConnected] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<OutlookEvent | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(() => {
    setLoading(true);
    const qs = new URLSearchParams({ days: "30" });
    if (query.trim()) qs.set("q", query.trim());
    api
      .get<OutlookCalendar>(`/workspace/microsoft/calendar?${qs.toString()}`)
      .then((d) => {
        setData(d);
        setNotConnected(false);
      })
      .catch(() => setNotConnected(true))
      .finally(() => setLoading(false));
  }, [query]);

  useEffect(load, [load, refreshKey]);

  function afterWrite() {
    setEditing(false);
    setCreating(false);
    setSelected(null);
    setRefreshKey((k) => k + 1);
  }

  // Grouped by day, because an agenda is read by day and never as a flat list.
  const byDay = new Map<string, OutlookEvent[]>();
  for (const e of data?.events ?? []) {
    const key = e.day ?? "undated";
    byDay.set(key, [...(byDay.get(key) ?? []), e]);
  }

  return (
    <ProviderWorkspace
      service="microsoft_calendar"
      title="Outlook Calendar"
      icon={<CalendarIcon />}
      parent={{ label: "Microsoft 365", to: "/connections/microsoft" }}
      refreshKey={refreshKey}
      assistant={MICROSOFT_ASSISTANT}
      activitySources={["Outlook Calendar"]}
      quickActions={
        <Button size="sm" variant="primary" onClick={() => { setCreating((v) => !v); setEditing(false); }}>
          {creating ? "Close" : "New event"}
        </Button>
      }
    >
      {creating && <EventComposer onDone={afterWrite} />}

      {notConnected ? (
        <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
          Outlook Calendar isn't connected yet.
        </div>
      ) : (
        <>
          {(data?.conflicts.length ?? 0) > 0 && (
            <div className="mb-4 rounded-md border border-warn/40 bg-warn/5 px-3 py-2.5">
              <div className="text-caption font-semibold text-warn">
                {data!.conflicts.length} overlapping meeting{data!.conflicts.length === 1 ? "" : "s"}
              </div>
              <ul className="mt-1 flex flex-col gap-0.5">
                {data!.conflicts.map((c, i) => (
                  <li key={i} className="text-caption text-ink-dim">
                    “{c.a}” overlaps “{c.b}”
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            {/* ---- agenda ---- */}
            <div className="min-w-0">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search events…"
                className="mb-3 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
              />

              {loading ? (
                <LoadingBlock />
              ) : (data?.events.length ?? 0) === 0 ? (
                <div className="rounded-md border border-dashed border-border px-4 py-10 text-center text-caption text-ink-faint">
                  Nothing scheduled in the next 30 days.
                </div>
              ) : (
                <div className="flex flex-col gap-4">
                  {[...byDay.entries()].map(([day, events]) => (
                    <section key={day}>
                      <div className="mb-1.5 text-caption font-semibold uppercase tracking-wide text-ink-faint">
                        {day === "undated"
                          ? "Undated"
                          : new Date(day).toLocaleDateString([], {
                              weekday: "long", day: "numeric", month: "long",
                            })}
                      </div>
                      <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
                        {events.map((e) => (
                          <li key={e.id}>
                            <button
                              onClick={() => { setSelected(e); setEditing(false); }}
                              className={`flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors hover:bg-surface/60 ${
                                selected?.id === e.id ? "bg-surface/70" : ""
                              }`}
                            >
                              <span className="w-14 flex-none pt-0.5 text-caption tabular-nums text-ink-faint">
                                {e.start
                                  ? new Date(e.start).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                                  : "—"}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span
                                  className={`block truncate text-small ${
                                    e.status === "cancelled" ? "text-ink-faint line-through" : "font-medium text-ink"
                                  }`}
                                >
                                  {e.title}
                                </span>
                                <span className="block truncate text-caption text-ink-faint">
                                  {e.attendee_count > 0
                                    ? `${e.attendee_count} attendee${e.attendee_count === 1 ? "" : "s"}`
                                    : "Just you"}
                                  {e.has_meeting_link ? " · online" : ""}
                                </span>
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    </section>
                  ))}
                </div>
              )}
            </div>

            {/* ---- detail + actions ---- */}
            <div className="min-w-0">
              {!selected ? (
                <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-caption text-ink-faint">
                  Select an event to see it here.
                </div>
              ) : (
                <div className="card">
                  <h2 className="text-lead font-semibold leading-tight text-ink text-balance">{selected.title}</h2>
                  <div className="mt-1 text-caption text-ink-faint">
                    {selected.start &&
                      new Date(selected.start).toLocaleString([], {
                        weekday: "short", day: "numeric", month: "short",
                        hour: "2-digit", minute: "2-digit",
                      })}
                    {selected.end &&
                      ` – ${new Date(selected.end).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`}
                  </div>

                  {selected.attendee_emails.length > 0 && (
                    <div className="mt-2 text-caption text-ink-dim">
                      <span className="text-ink-faint">Attendees: </span>
                      {selected.attendee_emails.join(", ")}
                    </div>
                  )}
                  {selected.organizer && (
                    <div className="mt-0.5 text-caption text-ink-faint">Organizer: {selected.organizer}</div>
                  )}

                  <div className="mt-3 flex flex-wrap items-center gap-2 border-y border-border py-2.5">
                    <Button size="sm" onClick={() => setEditing((v) => !v)}>
                      {editing ? "Cancel edit" : "Edit"}
                    </Button>
                    <ActionButton
                      actionType="outlook.cancel_event"
                      params={{
                        event_id: selected.event_id,
                        title: selected.title,
                        attendee_count: selected.attendee_count,
                      }}
                      label="Cancel meeting"
                      onDone={afterWrite}
                    />
                    {selected.meet_url && (
                      <a
                        href={selected.meet_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-caption text-ink-dim underline underline-offset-2 hover:text-ink"
                      >
                        Join <Icon name="external" size={12} />
                      </a>
                    )}
                    {selected.url && (
                      <a
                        href={selected.url}
                        target="_blank"
                        rel="noreferrer"
                        className="ml-auto inline-flex items-center gap-1 text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
                      >
                        Open in Outlook <Icon name="external" size={12} />
                      </a>
                    )}
                  </div>

                  {editing && <EventEditor event={selected} onDone={afterWrite} />}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </ProviderWorkspace>
  );
}

/** Local datetime-input value ("YYYY-MM-DDTHH:mm") from an ISO string. */
function toLocalInput(iso: string | null, fallbackHoursAhead = 1): string {
  const d = iso ? new Date(iso) : new Date(Date.now() + fallbackHoursAhead * 3600_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function EventComposer({ onDone }: { onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [start, setStart] = useState(toLocalInput(null, 1));
  const [end, setEnd] = useState(toLocalInput(null, 2));
  const [attendees, setAttendees] = useState("");

  const attendeeList = attendees.split(",").map((s) => s.trim()).filter(Boolean);
  const ready = title.trim().length > 0 && new Date(end) > new Date(start);

  return (
    <div className="card mb-4">
      <div className="mb-2 text-small font-semibold text-ink">New event</div>
      <div className="flex flex-col gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <div className="flex flex-wrap gap-2">
          <label className="flex-1 text-caption text-ink-faint">
            Starts
            <input
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="mt-0.5 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
            />
          </label>
          <label className="flex-1 text-caption text-ink-faint">
            Ends
            <input
              type="datetime-local"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className="mt-0.5 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
            />
          </label>
        </div>
        <input
          value={attendees}
          onChange={(e) => setAttendees(e.target.value)}
          placeholder="Attendees (comma-separated) — optional"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            actionType="outlook.create_event"
            params={{
              title,
              start: new Date(start).toISOString(),
              end: new Date(end).toISOString(),
              attendee_emails: attendeeList,
            }}
            label="Create event"
            confirmLabel="Create"
            variant="primary"
            undoable
            disabled={!ready}
            onDone={onDone}
          />
          <span className="text-caption text-ink-faint">
            {attendeeList.length > 0
              ? `${attendeeList.length} attendee(s) will be invited — you'll confirm first.`
              : "Just for you. Undoable."}
          </span>
        </div>
      </div>
    </div>
  );
}

function EventEditor({ event, onDone }: { event: OutlookEvent; onDone: () => void }) {
  const [title, setTitle] = useState(event.title);
  const [start, setStart] = useState(toLocalInput(event.start));
  const [end, setEnd] = useState(toLocalInput(event.end));
  const [attendees, setAttendees] = useState(event.attendee_emails.join(", "));

  const attendeeList = attendees.split(",").map((s) => s.trim()).filter(Boolean);
  const changed =
    title !== event.title ||
    new Date(start).toISOString() !== event.start ||
    new Date(end).toISOString() !== event.end ||
    attendeeList.join(",") !== event.attendee_emails.join(",");

  return (
    <div className="mt-3 rounded-md border border-border p-3">
      <div className="flex flex-col gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
        />
        <div className="flex flex-wrap gap-2">
          <label className="flex-1 text-caption text-ink-faint">
            Starts
            <input
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="mt-0.5 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
            />
          </label>
          <label className="flex-1 text-caption text-ink-faint">
            Ends
            <input
              type="datetime-local"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className="mt-0.5 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
            />
          </label>
        </div>
        <input
          value={attendees}
          onChange={(e) => setAttendees(e.target.value)}
          placeholder="Attendees (comma-separated)"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            actionType="outlook.update_event"
            params={{
              event_id: event.event_id,
              title,
              start: new Date(start).toISOString(),
              end: new Date(end).toISOString(),
              attendee_emails: attendeeList,
            }}
            label="Save changes"
            confirmLabel="Apply"
            variant="primary"
            undoable
            disabled={!changed}
            onDone={onDone}
          />
          <span className="text-caption text-ink-faint">
            {attendeeList.length > 0 ? "Attendees will be notified." : "Undoable — the previous values are kept."}
          </span>
        </div>
      </div>
    </div>
  );
}
