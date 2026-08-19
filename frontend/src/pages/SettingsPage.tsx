import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Connection } from "../api/types";
import { BackNav } from "../components/BackNav";
import { PROVIDER_LABEL } from "../components/situations";
import { Card, SkeletonRows } from "../components/ui";

/**
 * What Sentinel watches for.
 *
 * This page used to list seven invented "agents" (Engineering, Knowledge, HR
 * Wellbeing…) tagged PHASE 1 / PHASE 2 / PHASE 3 / PHASE 4 - our roadmap
 * leaking onto a screen a user opens - each with a toggle wired to nothing.
 * Both halves were fiction: no such agents exist, and there is no endpoint to
 * enable or disable anything.
 *
 * What does exist is a fixed set of detectors in the attention engine. So the
 * page now names those, honestly, and gets the only real variable - whether
 * the provider each one reads is connected - from /connections. A row is
 * active because a connection exists, not because someone flipped a switch.
 */
type Watch = {
  name: string;
  desc: string;
  /** Any one of these being connected is enough for the detector to fire. */
  providers: string[];
};

const WATCHES: Watch[] = [
  {
    name: "Mail you haven't answered",
    desc: "Someone wrote to you directly, you opened it, and it's been sitting since.",
    providers: ["gmail", "microsoft_outlook_mail"],
  },
  {
    name: "Mail that looks important",
    desc: "Flagged, starred, or from someone you reply to quickly.",
    providers: ["gmail", "microsoft_outlook_mail"],
  },
  {
    name: "Meetings coming up",
    desc: "The next day of your calendar, with what you'd want to have read first.",
    providers: ["google_calendar", "microsoft_outlook_calendar", "zoom"],
  },
  {
    name: "Deadlines",
    desc: "Dates named in mail, tasks and calendar entries that are close.",
    providers: ["gmail", "microsoft_outlook_mail", "microsoft_todo", "google_calendar"],
  },
  {
    name: "Tasks overdue or due today",
    desc: "Anything past its date, and anything that lands before tonight.",
    providers: ["microsoft_todo"],
  },
  {
    name: "Pull requests going stale",
    desc: "Open, waiting on review, and no longer moving.",
    providers: ["github"],
  },
  {
    name: "Being asked for directly",
    desc: "Messages that name you and expect something back.",
    providers: ["slack", "microsoft_teams"],
  },
  {
    name: "Blockers in conversation",
    desc: "Someone said they're stuck, blocked, or waiting on a person.",
    providers: ["slack", "microsoft_teams"],
  },
  {
    name: "Urgency in conversation",
    desc: "Language that reads as time-critical rather than routine.",
    providers: ["slack", "microsoft_teams"],
  },
];

export function SettingsPage() {
  const [connections, setConnections] = useState<Connection[] | null>(null);

  useEffect(() => {
    api
      .get<Connection[]>("/connections")
      .then(setConnections)
      .catch(() => setConnections([]));
  }, []);

  const connected = new Set((connections ?? []).map((c) => c.provider as string));
  const isActive = (w: Watch) => w.providers.some((p) => connected.has(p));

  const active = WATCHES.filter(isActive);
  const dormant = WATCHES.filter((w) => !isActive(w));

  return (
    <div className="max-w-2xl">
      <BackNav back={{ to: "/", label: "Dashboard" }} />
      <p className="eyebrow mb-2.5">Personal</p>
      <div className="section-head">
        <h1>What Sentinel watches for</h1>
        <p>
          Each of these runs against the services you've connected. Connect or disconnect a service
          on the <Link to="/" className="link">Dashboard</Link> to change what's checked.
        </p>
      </div>

      {connections === null ? (
        <SkeletonRows rows={6} />
      ) : (
        <>
          <Section
            label={active.length > 0 ? `Running · ${active.length}` : "Running"}
            watches={active}
            connected={connected}
            empty="Nothing is running yet — connect a service to give Sentinel something to read."
          />
          {dormant.length > 0 && (
            <Section
              label={`Waiting on a connection · ${dormant.length}`}
              watches={dormant}
              connected={connected}
              muted
            />
          )}
        </>
      )}
    </div>
  );
}

function Section({
  label,
  watches,
  connected,
  muted,
  empty,
}: {
  label: string;
  watches: Watch[];
  connected: Set<string>;
  muted?: boolean;
  empty?: string;
}) {
  return (
    <section className="mb-8">
      <p className="eyebrow mb-2.5">{label}</p>
      {watches.length === 0 ? (
        <p className="text-small text-ink-faint">{empty}</p>
      ) : (
        <Card padded={false}>
          {watches.map((w) => {
            // Name the services this actually reads. When it's running we show
            // the ones that are connected; when it isn't, we show what it would
            // take - that answer is the entire reason someone opens this page.
            const live = w.providers.filter((p) => connected.has(p));
            const shown = (live.length > 0 ? live : w.providers).map(
              (p) => PROVIDER_LABEL[p] ?? p,
            );
            return (
              <div key={w.name} className="border-b border-border p-3.5 last:border-b-0">
                <div className="flex items-baseline justify-between gap-3">
                  <p className={`text-small font-medium ${muted ? "text-ink-dim" : "text-ink"}`}>
                    {w.name}
                  </p>
                  <span className="flex-none text-micro text-ink-faint">
                    {live.length > 0 ? shown.join(" · ") : `Needs ${shown.join(" or ")}`}
                  </span>
                </div>
                <p className="mt-0.5 text-caption text-ink-faint">{w.desc}</p>
              </div>
            );
          })}
        </Card>
      )}
    </section>
  );
}
