import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Connection } from "../api/types";
import { BackNav } from "../components/BackNav";
import { MeetingBriefPanel, useMeetingBrief } from "../components/MeetingBriefPanel";

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
      <div className="max-w-lg rounded-md border border-dashed border-border-strong p-10 text-center text-ink-dim">
        <BackNav
          back={{ to: "/connections/google", label: "Google Workspace" }}
          crumbs={[{ label: "Dashboard", to: "/" }, { label: "Google", to: "/connections/google" }, { label: "Meet" }]}
        />
        <p className="mb-3 text-lead">Google Calendar isn't connected yet.</p>
        <Link to="/connections/google" className="text-body font-semibold text-accent-text hover:underline">
          Connect Google &rarr;
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      <BackNav
        back={{ to: "/connections/google", label: "Google Workspace" }}
        crumbs={[{ label: "Dashboard", to: "/" }, { label: "Google", to: "/connections/google" }, { label: "Meet" }]}
      />
      <h1 className="mb-1 text-h2 font-semibold text-balance">Meet</h1>
      <p className="mb-6 text-body text-ink-dim">
        Meeting history, built from your Calendar events — duration and attendees reflect what was
        scheduled, not real call attendance (Google doesn't expose that for personal accounts).
      </p>

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
            className="rounded-lg border border-border bg-surface shadow-card px-3 py-1.5 text-small outline-none focus:border-accent"
          />
          <button onClick={load} className="rounded-lg border border-border bg-surface shadow-card px-3 py-1.5 text-caption font-semibold text-ink-dim hover:border-accent hover:text-ink">
            Search
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-ink-dim">Loading&hellip;</div>
      ) : meetings.length === 0 ? (
        <div className="rounded-md border border-dashed border-border-strong p-8 text-center text-body text-ink-faint">
          No {range} meetings.
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-surface shadow-card">
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
                    <button
                      onClick={() => {
                        setPrepId(m.id);
                        brief.clear();
                        void brief.load(`/meetings/${m.id}/prepare`);
                      }}
                      disabled={brief.loading && prepId === m.id}
                      className={`font-mono text-caption underline underline-offset-2 disabled:opacity-50 ${
                        prepId === m.id ? "text-accent-text" : "text-ink-faint hover:text-ink"
                      }`}
                    >
                      {brief.loading && prepId === m.id ? "Preparing…" : "Prepare Me ✨"}
                    </button>
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
    </div>
  );
}

function durationLabel(start: string, end: string): string {
  const minutes = Math.round((Date.parse(end) - Date.parse(start)) / 60000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest > 0 ? `${hours}h ${rest}m` : `${hours}h`;
}
