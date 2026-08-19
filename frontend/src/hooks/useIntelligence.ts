import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type {
  AttentionItem,
  CatchUp,
  Connection,
  DecisionRow,
  Goal,
  MemoryRow,
  SentinelStatus,
  SituationRow,
} from "../api/types";
import { useWorkspace } from "../context/WorkspaceContext";

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
  loading: boolean;
  /** True when every call failed - the difference between "quiet" and "down". */
  offline: boolean;
  reload: () => Promise<void>;
  /** Local, optimistic removal so a resolved row leaves both surfaces at once. */
  dropAttention: (id: string) => void;
  restoreAttention: (item: AttentionItem) => void;
  dropDecision: (id: string) => void;
}

export function useIntelligence(): Intelligence {
  const { active } = useWorkspace();

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

  const reload = useCallback(async () => {
    setLoading(true);
    // Each call is non-fatal on its own: one dead endpoint should dim one
    // section, never blank the surface someone opens first every morning.
    let failures = 0;
    const fail = <T,>(fallback: T) => (): T => {
      failures += 1;
      return fallback;
    };

    const [st, sits, items, decs, mems, conns, recap, gls] = await Promise.all([
      api.get<SentinelStatus>("/attention/status").catch(fail(null)),
      api.get<SituationRow[]>("/situations?status=open").catch(fail([])),
      api.get<AttentionItem[]>("/attention").catch(fail([])),
      api.get<DecisionRow[]>("/decisions").catch(fail([])),
      api.get<MemoryRow[]>("/memory").catch(fail([])),
      api.get<Connection[]>("/connections").catch(fail([])),
      api.get<CatchUp>("/attention/catchup").catch(fail(null)),
      api.get<Goal[]>("/goals").catch(fail([])),
    ]);

    setStatus(st);
    setSituations(sits);
    setAttention(items);
    setDecisions(decs);
    setMemories(mems.filter((m) => m.status === "active"));
    setConnections(conns);
    setCatchup(recap);
    setGoals(gls.filter((g) => !g.closed_at));
    setOffline(failures === 8);
    setLoading(false);
  }, []);

  useEffect(() => {
    void reload();
    // Re-reads when the workspace changes: scope is a server-side concept and
    // every one of these endpoints answers differently under a different one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id]);

  return {
    status,
    situations,
    attention,
    decisions,
    memories,
    goals,
    connections,
    catchup,
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
