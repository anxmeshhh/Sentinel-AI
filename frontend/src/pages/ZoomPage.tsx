import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { ZoomAccount, ZoomMeeting, ZoomMeetingDetail, ZoomParticipants, ZoomRecordings } from "../api/types";
import { ZoomIcon } from "../components/ProviderIcons";
import { ActionButton, ProviderWorkspace } from "../components/workspace/ProviderWorkspace";
import { Button, Icon, LoadingBlock } from "../components/ui";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type Tab = "upcoming" | "past" | "recordings";

/** Zoom as a workspace: browse and search meetings, inspect one, schedule, edit
 *  and delete - all without leaving Sentinel. Sixth page on the shared shell. */
export function ZoomPage() {
  const [tab, setTab] = useState<Tab>("upcoming");
  const [meetings, setMeetings] = useState<ZoomMeeting[]>([]);
  const [account, setAccount] = useState<ZoomAccount | null>(null);
  const [recordings, setRecordings] = useState<ZoomRecordings | null>(null);
  const [loading, setLoading] = useState(true);
  const [notConnected, setNotConnected] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ZoomMeeting | null>(null);
  const [scheduling, setScheduling] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(() => {
    setLoading(true);
    if (tab === "recordings") {
      api
        .get<ZoomRecordings>("/workspace/zoom/recordings")
        .then((d) => { setRecordings(d); setNotConnected(false); })
        .catch(() => setNotConnected(true))
        .finally(() => setLoading(false));
      return;
    }
    const qs = new URLSearchParams({ filter: tab });
    if (query.trim()) qs.set("q", query.trim());
    api
      .get<ZoomMeeting[]>(`/workspace/zoom/meetings?${qs.toString()}`)
      .then((d) => {
        setMeetings(d);
        setNotConnected(false);
        setSelected((cur) => (cur ? d.find((m) => m.meeting_id === cur.meeting_id) ?? null : null));
      })
      .catch(() => setNotConnected(true))
      .finally(() => setLoading(false));
  }, [tab, query]);

  useEffect(load, [load, refreshKey]);

  // Capabilities are asked once - they describe the account, not the view.
  useEffect(() => {
    api.get<ZoomAccount>("/workspace/zoom/account").then(setAccount).catch(() => setAccount(null));
  }, [refreshKey]);

  function afterWrite() {
    setScheduling(false);
    setRefreshKey((k) => k + 1);
  }

  return (
    <ProviderWorkspace
      service="zoom"
      title="Zoom"
      icon={<ZoomIcon />}
      parent={{ label: "Dashboard", to: "/" }}
      refreshKey={refreshKey}
      activitySources={["Zoom"]}
      quickActions={
        <Button size="sm" variant="primary" onClick={() => setScheduling((v) => !v)}>
          {scheduling ? "Close" : "Schedule meeting"}
        </Button>
      }
    >
      {scheduling && <MeetingComposer onDone={afterWrite} timezone={account?.timezone} />}

      {notConnected ? (
        <ZoomConnect />
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <nav className="flex items-center gap-1" role="tablist">
              {(["upcoming", "past", "recordings"] as Tab[]).map((t) => (
                <button
                  key={t}
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => { setTab(t); setSelected(null); }}
                  className={`rounded-md px-2.5 py-1.5 text-caption capitalize transition-colors ${
                    tab === t ? "bg-surface-2 text-ink" : "text-ink-faint hover:text-ink"
                  }`}
                >
                  {t}
                </button>
              ))}
            </nav>
            {tab !== "recordings" && (
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search meetings…"
                className="ml-auto min-w-[10rem] flex-1 rounded-md border border-border bg-surface px-2.5 py-1 text-caption text-ink placeholder:text-ink-faint"
              />
            )}
          </div>

          {tab === "recordings" ? (
            <RecordingList data={recordings} loading={loading} />
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
              <div className="min-w-0">
                {loading ? (
                  <LoadingBlock />
                ) : meetings.length === 0 ? (
                  <div className="rounded-md border border-dashed border-border px-4 py-10 text-center text-caption text-ink-faint">
                    {tab === "upcoming" ? "No upcoming meetings." : "No past meetings in the synced window."}
                  </div>
                ) : (
                  <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
                    {meetings.map((m) => (
                      <li key={m.meeting_id}>
                        <button
                          onClick={() => setSelected(m)}
                          className={`flex w-full flex-col gap-0.5 px-3 py-2.5 text-left transition-colors hover:bg-surface/60 ${
                            selected?.meeting_id === m.meeting_id ? "bg-surface/70" : ""
                          }`}
                        >
                          <span className="truncate text-small text-ink">{m.topic}</span>
                          <span className="truncate text-caption text-ink-faint">{formatWhen(m.start)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="min-w-0">
                {selected ? (
                  <MeetingDetail meeting={selected} account={account} onDone={afterWrite} />
                ) : (
                  <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-caption text-ink-faint">
                    Select a meeting to see it here.
                  </div>
                )}
              </div>
            </div>
          )}

          {account && <CapabilityNotes account={account} />}
        </>
      )}
    </ProviderWorkspace>
  );
}

/** The full-page OAuth redirect can't carry an auth header, so it goes through
 *  the same short-lived connect ticket every other provider here uses. */
function ZoomConnect() {
  const [connecting, setConnecting] = useState(false);
  const error = new URLSearchParams(window.location.search).get("zoom_error");

  async function connect() {
    setConnecting(true);
    try {
      const { ticket } = await api.post<{ ticket: string }>("/integrations/zoom/connect-ticket");
      window.location.href = `${API_BASE}/integrations/zoom/connect?ticket=${encodeURIComponent(ticket)}&return_to=/zoom`;
    } catch {
      setConnecting(false);
    }
  }

  return (
    <div className="rounded-md border border-dashed border-border px-6 py-16 text-center">
      <div className="text-body text-ink">Zoom isn't connected yet</div>
      <p className="mx-auto mt-1 max-w-md text-caption leading-relaxed text-ink-faint">
        {error === "installed_now_connect"
          ? "The app was installed on your Zoom account, but that install came from Zoom rather than from here, so Sentinel couldn't tell it was you. Click Connect to finish."
          : error === "declined"
            ? "Zoom didn't complete the authorization. You can try again."
            : "Connect your Zoom account to see your meetings, schedule and edit them from here, and read recordings where your plan allows."}
      </p>
      <button onClick={connect} disabled={connecting} className="btn-primary mt-4">
        {connecting ? "Opening Zoom…" : "Connect Zoom"}
      </button>
    </div>
  );
}

function formatWhen(iso: string | null): string {
  if (!iso) return "No fixed time";
  const d = new Date(iso);
  return d.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

/** What this account can and cannot do, stated as capabilities rather than
 *  surfaced as errors when a plan-gated feature is missing. */
function CapabilityNotes({ account }: { account: ZoomAccount }) {
  const gated = Object.values(account.capabilities).filter((c) => c.state !== "available");
  if (gated.length === 0) return null;
  return (
    <div className="mt-4 rounded-md border border-dashed border-border px-3 py-2.5">
      <div className="text-caption font-semibold text-ink-dim">About this Zoom account</div>
      <ul className="mt-1 flex flex-col gap-1">
        {gated.map((c) => (
          <li key={c.label} className="text-caption text-ink-faint">
            <span className="text-ink-dim">{c.label}:</span> {c.detail}
          </li>
        ))}
      </ul>
    </div>
  );
}

function MeetingDetail({
  meeting,
  account,
  onDone,
}: {
  meeting: ZoomMeeting;
  account: ZoomAccount | null;
  onDone: () => void;
}) {
  const [detail, setDetail] = useState<ZoomMeetingDetail | null>(null);
  const [people, setPeople] = useState<ZoomParticipants | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    setDetail(null);
    setEditing(false);
    api.get<ZoomMeetingDetail>(`/workspace/zoom/meetings/${meeting.meeting_id}`).then(setDetail).catch(() => setDetail(null));
  }, [meeting.meeting_id]);

  useEffect(() => {
    setPeople(null);
    // Attendance only exists for a meeting that has actually run.
    if (meeting.upcoming || !meeting.uuid) return;
    api
      .get<ZoomParticipants>(`/workspace/zoom/past/${encodeURIComponent(meeting.uuid)}/participants`)
      .then(setPeople)
      .catch(() => setPeople(null));
  }, [meeting.uuid, meeting.upcoming]);

  return (
    <div className="card">
      <h2 className="text-lead font-semibold leading-tight text-ink text-balance">{meeting.topic}</h2>
      <div className="mt-1 text-caption text-ink-faint">
        {formatWhen(meeting.start)}
        {detail?.duration ? ` · ${detail.duration} min` : ""}
        {meeting.host ? ` · hosted by ${meeting.host}` : ""}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-y border-border py-2.5">
        <Button size="sm" onClick={() => setEditing((v) => !v)}>
          {editing ? "Cancel edit" : "Edit"}
        </Button>
        <ActionButton
          actionType="zoom.delete_meeting"
          params={{ meeting_id: meeting.meeting_id, topic: meeting.topic, notify: true }}
          label="Delete"
          confirmLabel="Delete"
          onDone={onDone}
        />
        {meeting.join_url && (
          <a
            href={meeting.join_url}
            target="_blank"
            rel="noreferrer"
            className="ml-auto inline-flex items-center gap-1 text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
          >
            Join <Icon name="external" size={12} />
          </a>
        )}
      </div>

      {editing && <MeetingEditor meeting={meeting} detail={detail} onDone={() => { setEditing(false); onDone(); }} />}

      {detail?.agenda && (
        <div className="mt-3">
          <div className="text-caption font-semibold uppercase tracking-wide text-ink-faint">Agenda</div>
          <p className="mt-1 whitespace-pre-wrap text-small leading-relaxed text-ink-dim">{detail.agenda}</p>
        </div>
      )}

      {!meeting.upcoming && (
        <div className="mt-3">
          <div className="text-caption font-semibold uppercase tracking-wide text-ink-faint">Attendance</div>
          {people === null ? (
            <p className="mt-1 text-caption text-ink-faint">…</p>
          ) : !people.available ? (
            <p className="mt-1 text-caption text-ink-faint">{people.reason}</p>
          ) : people.participants.length === 0 ? (
            <p className="mt-1 text-caption text-ink-faint">Nobody joined this meeting.</p>
          ) : (
            <ul className="mt-1 flex flex-col gap-1">
              {people.participants.map((p, i) => (
                <li key={i} className="flex items-baseline justify-between gap-2 text-caption">
                  <span className="truncate text-ink-dim">{p.name || p.email || "Unknown"}</span>
                  {p.duration != null && <span className="flex-none text-ink-faint">{Math.round(p.duration / 60)} min</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {account?.capabilities.recordings.state !== "available" && !meeting.upcoming && (
        <p className="mt-3 text-caption text-ink-faint">{account?.capabilities.recordings.detail}</p>
      )}
    </div>
  );
}

function MeetingComposer({ onDone, timezone }: { onDone: () => void; timezone?: string }) {
  const [topic, setTopic] = useState("");
  const [start, setStart] = useState("");
  const [duration, setDuration] = useState(30);
  const [agenda, setAgenda] = useState("");

  return (
    <div className="card mb-4">
      <div className="mb-2 text-small font-semibold text-ink">Schedule a meeting</div>
      <div className="flex flex-col gap-2">
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="Topic"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <div className="flex flex-wrap gap-2">
          <input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="flex-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
          />
          <input
            type="number"
            min={1}
            max={1440}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            className="w-24 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
            aria-label="Duration in minutes"
          />
        </div>
        <textarea
          value={agenda}
          onChange={(e) => setAgenda(e.target.value)}
          rows={3}
          placeholder="Agenda (optional)"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            actionType="zoom.create_meeting"
            params={{
              topic,
              // datetime-local has no zone; the browser's own offset is the
              // honest interpretation of what the user just typed.
              start: start ? new Date(start).toISOString() : null,
              duration,
              agenda,
              timezone_name: timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
            }}
            label="Schedule"
            confirmLabel="Schedule"
            variant="primary"
            undoable
            disabled={topic.trim().length === 0 || !start}
            onDone={onDone}
          />
          <span className="text-caption text-ink-faint">Creates a real Zoom meeting. Nobody is invited.</span>
        </div>
      </div>
    </div>
  );
}

function MeetingEditor({
  meeting,
  detail,
  onDone,
}: {
  meeting: ZoomMeeting;
  detail: ZoomMeetingDetail | null;
  onDone: () => void;
}) {
  const [topic, setTopic] = useState(meeting.topic);
  const [start, setStart] = useState(meeting.start ? toLocalInput(meeting.start) : "");
  const [duration, setDuration] = useState(detail?.duration ?? 30);
  const [agenda, setAgenda] = useState(detail?.agenda ?? "");

  return (
    <div className="mt-3 flex flex-col gap-2 rounded-md border border-border p-3">
      <input
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
        className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
      />
      <div className="flex flex-wrap gap-2">
        <input
          type="datetime-local"
          value={start}
          onChange={(e) => setStart(e.target.value)}
          className="flex-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
        />
        <input
          type="number"
          min={1}
          max={1440}
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
          className="w-24 rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink"
          aria-label="Duration in minutes"
        />
      </div>
      <textarea
        value={agenda}
        onChange={(e) => setAgenda(e.target.value)}
        rows={3}
        placeholder="Agenda"
        className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
      />
      <div className="flex flex-wrap items-center gap-2">
        <ActionButton
          actionType="zoom.update_meeting"
          params={{
            meeting_id: meeting.meeting_id,
            topic,
            start: start ? new Date(start).toISOString() : null,
            duration,
            agenda,
          }}
          label="Save changes"
          confirmLabel="Save"
          variant="primary"
          undoable
          onDone={onDone}
        />
        <span className="text-caption text-ink-faint">Undo restores the previous topic, time and agenda.</span>
      </div>
    </div>
  );
}

function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function RecordingList({ data, loading }: { data: ZoomRecordings | null; loading: boolean }) {
  const [transcript, setTranscript] = useState<Record<string, string>>({});

  if (loading && !data) return <LoadingBlock />;
  if (!data) return null;

  if (!data.available) {
    return (
      <div className="rounded-md border border-dashed border-border px-6 py-12 text-center">
        <div className="text-small font-semibold text-ink">Recordings aren't available here</div>
        <p className="mx-auto mt-1 max-w-md text-caption leading-relaxed text-ink-faint">{data.reason}</p>
      </div>
    );
  }

  if (data.recordings.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border px-4 py-10 text-center text-caption text-ink-faint">
        No cloud recordings in the last 30 days.
      </div>
    );
  }

  function openTranscript(uuid: string) {
    setTranscript((t) => ({ ...t, [uuid]: "…" }));
    api
      .get<{ available: boolean; reason: string | null; text: string }>(
        `/workspace/zoom/recordings/${encodeURIComponent(uuid)}/transcript`,
      )
      .then((d) => setTranscript((t) => ({ ...t, [uuid]: d.available ? d.text : d.reason || "No transcript." })))
      .catch(() => setTranscript((t) => ({ ...t, [uuid]: "Couldn't load that transcript." })));
  }

  return (
    <ul className="flex flex-col gap-3">
      {data.recordings.map((r) => (
        <li key={r.uuid} className="card">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-small font-medium text-ink">{r.topic}</span>
            <span className="text-caption text-ink-faint">{formatWhen(r.start)}</span>
          </div>
          <div className="mt-1 text-caption text-ink-faint">
            {r.duration != null ? `${r.duration} min` : "—"}
            {r.total_size != null ? ` · ${(r.total_size / 1024 / 1024).toFixed(1)} MB` : ""}
            {` · ${r.files.length} file${r.files.length === 1 ? "" : "s"}`}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {r.share_url && (
              <a
                href={r.share_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
              >
                Open in Zoom <Icon name="external" size={12} />
              </a>
            )}
            {r.has_transcript && (
              <Button size="sm" onClick={() => openTranscript(r.uuid)}>
                Read transcript
              </Button>
            )}
          </div>
          {transcript[r.uuid] && (
            <p className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-surface px-3 py-2 text-caption leading-relaxed text-ink-dim">
              {transcript[r.uuid]}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}
