import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { AttentionItem } from "../api/types";
import {
  AttentionSection,
  ContextRail,
  Greeting,
  RecommendedCard,
  SignalCards,
  StatChips,
} from "../components/assistant/CommandCenter";
import { WorkspaceOverview } from "../components/WorkspaceOverview";
import { useAuth } from "../context/AuthContext";
import { useWorkspace } from "../context/WorkspaceContext";
import { openAttention, useIntelligence } from "../hooks/useIntelligence";
import { EmptyState, SkeletonRows } from "../components/ui";

/**
 * The Command Center.
 *
 * This page answers one question - "what matters right now, and what should I
 * do?" - and everything on it is ordered by how directly it answers that.
 *
 * It used to open with My Groups and My Channels: org structure, six cards each
 * saying "1 member · Org Admin", with the entire intelligence product reduced
 * to a strip above them. That is an admin console wearing a dashboard's name.
 * Group and channel management now lives where it belongs - the sidebar tree
 * for org workspaces - and this page is the intelligence.
 *
 * The argument, in order:
 *
 *   greeting     what state the workspace is in, in one line
 *   chips        the scale Sentinel is working at
 *   cards        Critical / Upcoming / Insight - the most synthesised things
 *   attention    the atomic things needing a person, ranked
 *   recommended  what to do, from the Decision Engine
 *   (rail)       what it remembers, what it watches
 *
 * There is no composer on this page any more - the floating Assistant button
 * (mounted once, globally, in App.tsx) is the one way into the one Assistant
 * from here. The rail's Quick Actions still hand a specific question to
 * /assistant via `handOff`, same as before; that is a navigation shortcut,
 * not a second place to type.
 */
export function BriefPage() {
  const { user } = useAuth();
  const { active } = useWorkspace();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const intel = useIntelligence();
  const [acting, setActing] = useState<string | null>(null);

  const open = openAttention(intel.attention);
  const topDecision = intel.decisions.find((d) => d.kind === "recommend") ?? intel.decisions[0];

  async function resolveFinding(item: AttentionItem, state: "done" | "snoozed") {
    intel.dropAttention(item.id);
    const body =
      state === "snoozed"
        ? { state, snoozed_until: new Date(Date.now() + 24 * 3600 * 1000).toISOString() }
        : { state };
    try {
      await api.patch(`/attention/${item.id}`, body);
    } catch {
      intel.restoreAttention(item); // restore on failure
    }
  }

  async function decide(id: string, verb: "confirm" | "dismiss") {
    setActing(id);
    try {
      await api.post(`/decisions/${id}/${verb}`);
      intel.dropDecision(id);
    } finally {
      setActing(null);
    }
  }

  /** Hand the question to the Assistant rather than answering it here. */
  function handOff(question: string) {
    const q = question.trim();
    if (!q) return;
    navigate(`/assistant?q=${encodeURIComponent(q)}`);
  }

  const connectedBanner = searchParams.get("connected");
  const googleError = searchParams.get("google_error");

  const subtitle = intel.loading
    ? "Reading your connected services…"
    : intel.offline
      ? "I can't reach Sentinel's services right now."
      : open.length === 0 && intel.situations.length === 0
        ? "Nothing needs your attention."
        : "Here's what needs your attention today.";

  return (
    <div className="flex gap-6">
      <div className="flex min-w-0 flex-1 flex-col">
        {connectedBanner === "google" && (
          <Banner tone="good" onDismiss={() => setSearchParams({})}>
            Google connected — Calendar and Gmail will start syncing on the next run.
          </Banner>
        )}
        {googleError && (
          <Banner tone="crit" onDismiss={() => setSearchParams({})}>
            {GOOGLE_ERROR_MESSAGES[googleError] ?? "Couldn't connect Google — try again."}
          </Banner>
        )}

        {active?.is_demo && (
          <div className="mb-5 rounded-lg border border-warn/40 bg-warn/5 px-4 py-3 text-caption text-warn">
            <b>Sample workspace.</b> Realistic demo data — no real account is connected. Detection and
            AI are genuinely running against it.
          </div>
        )}

        <div className="flex-1">
          <Greeting name={user?.name} subtitle={subtitle} />
          <StatChips intel={intel} />

          {intel.loading ? (
            <SkeletonRows rows={5} />
          ) : (
            <>
              <SignalCards
                intel={intel}
                open={open}
                onPrepare={() => handOff("Prepare me for my next meeting")}
              />

              {open.length === 0 ? (
                <EmptyState
                  compact
                  title="You're clear."
                  description={
                    intel.connections.length === 0
                      ? "Connect a service and Sentinel will start telling you what needs you."
                      : `Sentinel is watching ${intel.connections.length} ${
                          intel.connections.length === 1 ? "connection" : "connections"
                        } and nothing needs you right now.`
                  }
                />
              ) : (
                <AttentionSection
                  items={open.slice(0, 5)}
                  total={open.length}
                  onResolve={resolveFinding}
                />
              )}

              <RecommendedCard
                decision={topDecision}
                busy={acting === topDecision?.id}
                onDecide={decide}
              />
            </>
          )}
        </div>

        {/* Channels and connections: present and one click from anything, but
            below the intelligence rather than in front of it. */}
        {!intel.loading && <WorkspaceOverview connections={intel.connections} />}
      </div>

      <ContextRail intel={intel} onAsk={handOff} />
    </div>
  );
}

const GOOGLE_ERROR_MESSAGES: Record<string, string> = {
  session_expired: "That connect link expired — try connecting again.",
  no_refresh_token: "Google didn't return a refresh token — try connecting again.",
};

function Banner({
  tone,
  children,
  onDismiss,
}: {
  tone: "good" | "crit";
  children: string;
  onDismiss: () => void;
}) {
  return (
    <div
      className={`mb-5 flex items-center justify-between gap-3 rounded-lg border px-3.5 py-2.5 text-caption ${
        tone === "good" ? "border-good/40 bg-good/10 text-good" : "border-crit/40 bg-crit/10 text-crit"
      }`}
    >
      <span>{children}</span>
      <button onClick={onDismiss} aria-label="Dismiss" className="flex-none opacity-70 hover:opacity-100">
        ✕
      </button>
    </div>
  );
}
