import { useCallback, useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ChannelPrepare, MeetingBrief } from "../../api/types";
import { Button, Card, EmptyState, Icon, LoadingBlock } from "../ui";

/** Channel-contextual meeting prep: upcoming meetings the channel is
 *  authorized to see, each preparable into a grounded brief via the existing
 *  Phase 2u meeting_prep service (scoped to this channel's connections). */
export function PrepareModule({ teamId }: { teamId: string }) {
  const [data, setData] = useState<ChannelPrepare | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.get<ChannelPrepare>(`/teams/${teamId}/prepare`));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [teamId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingBlock />;
  if (!data || data.no_connections) {
    return (
      <EmptyState
        title="No meetings to prepare for"
        description="Prepare Me works from a calendar connection assigned to this channel. Assign Google Calendar in Extensions and upcoming meetings will appear here."
      />
    );
  }
  if (data.meetings.length === 0) {
    return (
      <EmptyState
        title="Nothing upcoming"
        description="No upcoming meetings in this channel's authorized calendar right now."
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-caption text-ink-faint">
        {data.meetings.length} upcoming meeting{data.meetings.length === 1 ? "" : "s"}. Prepare a grounded brief for any
        of them — Sentinel pulls only from this channel's authorized connections.
      </p>
      {data.meetings.map((m) => (
        <MeetingRow key={m.signal_id} teamId={teamId} meeting={m} />
      ))}
    </div>
  );
}

function MeetingRow({
  teamId,
  meeting,
}: {
  teamId: string;
  meeting: ChannelPrepare["meetings"][number];
}) {
  const [brief, setBrief] = useState<MeetingBrief | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [open, setOpen] = useState(false);

  async function prepare() {
    setPreparing(true);
    try {
      const b = await api.post<MeetingBrief>(`/teams/${teamId}/prepare/${meeting.signal_id}`);
      setBrief(b);
      setOpen(true);
    } finally {
      setPreparing(false);
    }
  }

  return (
    <Card padded={false} className="p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-small font-semibold text-ink">{meeting.title}</div>
          <div className="mt-0.5 text-micro text-ink-faint">
            {meeting.start ? new Date(meeting.start).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Time TBD"}
            {meeting.attendee_count > 0 && ` · ${meeting.attendee_count} attendee${meeting.attendee_count === 1 ? "" : "s"}`}
          </div>
        </div>
        <div className="flex flex-none items-center gap-2">
          {meeting.url && (
            <a href={meeting.url} target="_blank" rel="noreferrer" className="text-caption text-ink-faint hover:text-ink">
              <Icon name="external" size={14} />
            </a>
          )}
          {brief ? (
            <Button size="sm" variant="ghost" onClick={() => setOpen((o) => !o)}>
              {open ? "Hide brief" : "Show brief"}
            </Button>
          ) : (
            <Button size="sm" variant="secondary" onClick={prepare} loading={preparing}>
              Prepare me
            </Button>
          )}
        </div>
      </div>

      {brief && open && (
        <div className="mt-4 border-t border-rule pt-4">
          <p className="text-small leading-relaxed text-ink-dim">{brief.narrative}</p>
          {brief.prep_points.length > 0 && (
            <ul className="mt-3 flex flex-col gap-1.5">
              {brief.prep_points.map((point, i) => (
                <li key={i} className="flex gap-2 text-caption text-ink-dim">
                  <span className="flex-none text-ink-faint">→</span>
                  {point}
                </li>
              ))}
            </ul>
          )}
          {brief.sources.length > 0 && (
            <div className="mt-4">
              <div className="label-sub mb-1.5">Sources</div>
              <div className="flex flex-col gap-1">
                {brief.sources.map((src, i) => (
                  <a
                    key={i}
                    href={src.url ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-caption text-ink-dim transition-colors hover:border-border-strong hover:text-ink"
                  >
                    <span className="flex-none rounded-sm border border-rule-strong px-1.5 py-px font-mono text-micro text-ink-faint">
                      {src.kind}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{src.label}</span>
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
