import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Connection } from "../api/types";
import { MeetIcon } from "../components/ProviderIcons";
import { MeetingBriefPanel, useMeetingBrief } from "../components/MeetingBriefPanel";
import { GOOGLE_ASSISTANT } from "../components/workspace/assistantConfigs";
import { ProviderWorkspace } from "../components/workspace/ProviderWorkspace";
import { Button, LoadingBlock, PageHeader } from "../components/ui";

interface Meeting {
  id: string;
  title: string;
  start: string | null;
  end: string | null;
  occurred_at: string;
  attendee_count: number;
  attendee_emails: string[];
  status: "upcoming" | "past" | "cancelled";
  calendar_url: string | null;
  meet_url: string | null;
}

const STATUS_META: Record<Meeting["status"], { label: string; cls: string }> = {
  upcoming: { label: "Upcoming", cls: "border-good/40 text-good" },
  past: { label: "Completed", cls: "border-border text-ink-faint" },
  cancelled: { label: "Cancelled", cls: "border-crit/40 text-crit" },
};

export function MeetPage() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [range, setRange] = useState<"upcoming" | "past">("upcoming");
  const [search, setSearch] = useState("");
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [loading, setLoading] = useState(true);
  const [prepId, setPrepId] = useState<string | null>(null);
  const brief = useMeetingBrief();

  useEffect(() => {
    api
      .get<Connection[]>("/connections")
      .then((conns) => setConnected(conns.some((c) => c.provider === "google_calendar")))
      // See CalendarPage: an unhandled rejection here leaves `connected`
      // null and the page stuck in its loading state.
      .catch(() => setConnected(false));
  }, []);

  useEffect(() => {
    if (connected === false) {
      setLoading(false);
      return;
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range, connected]);

  async function load() {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ range, limit: "50" });
      if (search.trim()) qs.set("search", search.trim());
      const data = await api.get<Meeting[]>(`/meet/history?${qs.toString()}`);
      setMeetings(data);
    } catch {
      setMeetings([]);
    } finally {
      setLoading(false);
    }
  }

  if (connected === false) {
    return (
      <ProviderWorkspace
        service="google_calendar"
        title="Meet"
        icon={<MeetIcon />}
        parent={{ label: "Google Workspace", to: "/connections/google" }}
      >
        <div className="max-w-lg rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
          <p className="mb-3 text-lead">Google Calendar isn't connected yet.</p>
          <Link to="/connections/google" className="text-body font-semibold text-accent-text hover:underline">
            Connect Google &rarr;
          </Link>
        </div>
      </ProviderWorkspace>
    );
  }

  // Meet has no connection of its own - it rides on Calendar events that
  // carry a meeting link (the same fact meetHealth() in ConnectionWorkspacePage
  // encodes), so this page's shell is scoped to "google_calendar" throughout:
  // real Calendar connection status, real Calendar Sync Now, real Calendar
  // activity - never a fabricated "Meet" connection that doesn't exist.
  return (
    <ProviderWorkspace
      service="google_calendar"
      title="Meet"
      icon={<MeetIcon />}
      parent={{ label: "Google Workspace", to: "/connections/google" }}
      assistant={GOOGLE_ASSISTANT}
      activitySources={["Google Calendar"]}
    >
      <PageHeader
        eyebrow="Personal"
        title="Meet"
        description={<>Meeting history, built from your Calendar events — duration and attendees reflect what was
        scheduled, not real call attendance (Google doesn't expose that for personal accounts).</>}
      />

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1.5">
          {(["upcoming", "past"] as const).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`rounded-full border px-3 py-1.5 font-mono text-caption capitalize transition-colors ${
                range === r ? "border-accent bg-accent/15 text-accent-text" : "border-border text-ink-faint hover:text-ink"
              }`}
            >
              {r === "upcoming" ? "Upcoming Meetings" : "Past Meetings"}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load()}
            placeholder="Search meetings…"
            className="rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
          />
          <Button variant="secondary" size="sm" onClick={load} >
            Search
          </Button>
        </div>
      </div>

      {loading ? (
        <LoadingBlock />
      ) : meetings.length === 0 ? (
        <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
          No {range} meetings.
        </div>
      ) : (
        <div className="card">
          {meetings.map((m) => {
            const meta = STATUS_META[m.status];
            return (
              <div key={m.id} className="border-b border-border p-3.5 last:border-b-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-body font-semibold text-ink">{m.title}</div>
                    <div className="mt-0.5 text-caption text-ink-faint">
                      {m.start ? new Date(m.start).toLocaleString() : "—"}
                      {m.end && m.start && ` · ${durationLabel(m.start, m.end)}`}
                      {m.attendee_count > 0 && ` · ${m.attendee_count} attendee${m.attendee_count === 1 ? "" : "s"}`}
                    </div>
                  </div>
                  <span className={`flex-none rounded-full border px-2 py-[3px] font-mono text-micro uppercase tracking-wide ${meta.cls}`}>
                    {meta.label}
                  </span>
                </div>
                <div className="mt-2.5 flex gap-3">
                  {m.calendar_url && (
                    <a
                      href={m.calendar_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
                    >
                      Open Calendar Event
                    </a>
                  )}
                  {m.meet_url && (
                    <a
                      href={m.meet_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-caption text-good underline underline-offset-2 hover:opacity-80"
                    >
                      Open Meet Link
                    </a>
                  )}
                  {m.status === "upcoming" && (
                    <Button size="sm" variant="secondary" onClick={() => { setPrepId(m.id); brief.clear(); void brief.load(`/meetings/${m.id}/prepare`); }} disabled={brief.loading && prepId === m.id}>
                      {brief.loading && prepId === m.id ? "Preparing…" : "Prepare Me ✨"}
                    </Button>
                  )}
                </div>

                {prepId === m.id && (brief.brief || brief.error) && (
                  <div className="mt-3">
                    {brief.error ? (
                      <p className="text-small text-crit">{brief.error}</p>
                    ) : (
                      <MeetingBriefPanel
                        brief={brief.brief!}
                        refreshing={brief.refreshing}
                        onRefresh={() => brief.load(`/meetings/${m.id}/prepare`, { refresh: true })}
                        onClose={() => {
                          setPrepId(null);
                          brief.clear();
                        }}
                      />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </ProviderWorkspace>
  );
}

function durationLabel(start: string, end: string): string {
  const minutes = Math.round((Date.parse(end) - Date.parse(start)) / 60000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest > 0 ? `${hours}h ${rest}m` : `${hours}h`;
}
