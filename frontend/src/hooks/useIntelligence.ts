import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type {
  AttentionItem,
  CatchUp,
  Connection,
  DecisionRow,
  Goal,
  MemoryRow,
  SentinelStatus,
  Situation,
  SituationRow,
} from "../api/types";
import { useWorkspace } from "../context/WorkspaceContext";

/**
 * Which Sentinel is being asked.
 *
 * Personal and channel intelligence are the SAME engines run with a different
 * Scope (app/domain/scope.py) - never two systems. This mirrors that seam on
 * the client: the same hook, the same shapes, a different set of endpoints.
 *
 * Authorization is NOT decided here. Every channel endpoint re-checks
 * membership server-side (`require_channel_role`), so this only chooses which
 * question to ask; the server decides whether the caller may have the answer.
 */
export type AssistantScope =
  | { kind: "personal" }
  | { kind: "channel"; teamId: string; name: string };

export const PERSONAL_SCOPE: AssistantScope = { kind: "personal" };

/**
 * Everything the Intelligence Core currently knows, in one place.
 *
 * The Command Center and the Assistant answer the same question through
 * different surfaces, so they were both assembling the same six calls. Two
 * copies of that is two chances for them to disagree about what "open" means
 * or which endpoint is authoritative - and the whole product claim is that
 * there is one brain underneath.
 *
 * Nothing here interprets. It fetches what the engines already wrote and hands
 * it over; ranking, severity and correlation all stay server-side.
 */
export interface Intelligence {
  status: SentinelStatus | null;
  situations: SituationRow[];
  attention: AttentionItem[];
  decisions: DecisionRow[];
  memories: MemoryRow[];
  goals: Goal[];
  connections: Connection[];
  catchup: CatchUp | null;
  /** Fetched on demand, never on mount - see `loadCatchup`. */
  loadCatchup: () => Promise<CatchUp | null>;
  loading: boolean;
  /** True when every call failed - the difference between "quiet" and "down". */
  offline: boolean;
  reload: () => Promise<void>;
  /** Local, optimistic removal so a resolved row leaves both surfaces at once. */
  dropAttention: (id: string) => void;
  restoreAttention: (item: AttentionItem) => void;
  dropDecision: (id: string) => void;
}

export function useIntelligence(scope: AssistantScope = PERSONAL_SCOPE): Intelligence {
  const { active } = useWorkspace();
  const teamId = scope.kind === "channel" ? scope.teamId : null;

  const [status, setStatus] = useState<SentinelStatus | null>(null);
  const [situations, setSituations] = useState<SituationRow[]>([]);
  const [attention, setAttention] = useState<AttentionItem[]>([]);
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [memories, setMemories] = useState<MemoryRow[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [catchup, setCatchup] = useState<CatchUp | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);
  // Session-scoped guard for the catch-up fetch. A ref rather than state so
  // two components asking in the same tick cannot both fire the request.
  const fetchedCatchup = useRef(false);
  const catchupRef = useRef<CatchUp | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    // Each call is non-fatal on its own: one dead endpoint should dim one
    // section, never blank the surface someone opens first every morning.
    let failures = 0;
    const fail = <T,>(fallback: T) => (): T => {
      failures += 1;
      return fallback;
    };

    // Catch-up is deliberately NOT in this list. It is the one endpoint here
    // with a side effect: GET /attention/catchup advances the caller's
    // last-seen marker before it computes anything. Fetching it from every
    // mount of this hook (Dashboard, Attention, Situations, Assistant) reset
    // that marker several times a session, so the gap was almost always under
    // the 12h floor and the narrative came back null - the feature paid for an
    // LLM call and then mostly answered "nothing to report". It is now
    // requested only where it is actually shown, via `loadCatchup` below.

    // Channel scope swaps in the endpoints that already exist for a channel -
    // same engines, same shapes, membership re-checked server-side on each.
    // `/teams/{id}/briefing` builds its item list with the identical `_to_out`
    // that `/attention` uses, so an AttentionItem is an AttentionItem in
    // either scope and every renderer below works unchanged.
    if (teamId) {
      const [brief, sits, decs, mems, gls] = await Promise.all([
        api.get<{ items: AttentionItem[] }>(`/teams/${teamId}/briefing`).catch(fail(null)),
        api.get<Situation[]>(`/teams/${teamId}/proactive`).catch(fail([])),
        api.get<DecisionRow[]>(`/teams/${teamId}/decisions`).catch(fail([])),
        api.get<MemoryRow[]>(`/teams/${teamId}/memory`).catch(fail([])),
        api.get<Goal[]>(`/teams/${teamId}/goals`).catch(fail([])),
      ]);

      // A channel has no correlated-Situation route of its own, so its
      // situations come from the proactive engine and are projected onto the
      // same row shape. `providers` stays empty rather than guessed - the
      // proactive payload does not carry provider per evidence item, and an
      // invented chip would be worse than an absent one.
      setStatus(null);
      setSituations(
        (sits ?? []).map((s) => ({
          id: s.id,
          title: s.title,
          entity: null,
          entity_kind: null,
          severity: s.importance >= 0.9 ? "critical" : "review",
          status: s.status === "resolved" ? "resolved" : "open",
          member_count: s.evidence_count,
          cross_provider: false,
          occurrence_count: 1,
          providers: [],
          first_seen_at: s.first_seen_at,
          last_activity_at: s.last_evidence_at,
          resolved_at: null,
        })),
      );
      setAttention(brief?.items ?? []);
      setDecisions(decs);
      setMemories(mems.filter((m) => m.status === "active"));
      // A channel's connection list has its own shape and its own surface
      // (Extensions). Left empty here rather than approximated, so nothing
      // downstream reports a connection count it did not actually read.
      setConnections([]);
      setGoals(gls.filter((g) => !g.closed_at));
      setOffline(failures === 5);
      setLoading(false);
      return;
    }

    const [st, sits, items, decs, mems, conns, gls] = await Promise.all([
      api.get<SentinelStatus>("/attention/status").catch(fail(null)),
      api.get<SituationRow[]>("/situations?status=open").catch(fail([])),
      api.get<AttentionItem[]>("/attention").catch(fail([])),
      api.get<DecisionRow[]>("/decisions").catch(fail([])),
      api.get<MemoryRow[]>("/memory").catch(fail([])),
      api.get<Connection[]>("/connections").catch(fail([])),
      api.get<Goal[]>("/goals").catch(fail([])),
    ]);

    setStatus(st);
    setSituations(sits);
    setAttention(items);
    setDecisions(decs);
    setMemories(mems.filter((m) => m.status === "active"));
    setConnections(conns);
    setGoals(gls.filter((g) => !g.closed_at));
    setOffline(failures === 7);
    setLoading(false);
  }, [teamId]);

  /** Fetch the recap on demand, and remember it for the rest of the session.
   *  Cached because the marker-advancing side effect above means a second
   *  call in the same session would legitimately return an empty recap - the
   *  first call already consumed the window. */
  const loadCatchup = useCallback(async (): Promise<CatchUp | null> => {
    if (fetchedCatchup.current) return catchupRef.current;
    fetchedCatchup.current = true;
    const recap = await api.get<CatchUp>("/attention/catchup").catch(() => null);
    catchupRef.current = recap;
    setCatchup(recap);
    return recap;
  }, []);

  useEffect(() => {
    void reload();
    // Re-reads when the workspace changes: scope is a server-side concept and
    // every one of these endpoints answers differently under a different one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id, teamId]);

  return {
    status,
    situations,
    attention,
    decisions,
    memories,
    goals,
    connections,
    catchup,
    loadCatchup,
    loading,
    offline,
    reload,
    dropAttention: (id) => setAttention((l) => l.filter((i) => i.id !== id)),
    restoreAttention: (item) => setAttention((l) => [item, ...l]),
    dropDecision: (id) => setDecisions((l) => l.filter((d) => d.id !== id)),
  };
}

/** The open, unresolved items, highest priority first. The ordering is the
 *  engine's `priority`, never a heuristic invented on the client. */
export function openAttention(items: AttentionItem[]): AttentionItem[] {
  return items.filter((i) => i.state === "new").sort((a, b) => b.priority - a.priority);
}
