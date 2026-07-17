import type { ReactNode } from "react";
import { createContext, useContext, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Team } from "../api/types";
import { useWorkspace } from "./WorkspaceContext";

interface TeamContextValue {
  teams: Team[];
  loading: boolean;
  refresh: () => Promise<void>;
  join: (teamId: string) => Promise<void>;
  leave: (teamId: string) => Promise<void>;
}

const TeamContext = createContext<TeamContextValue | null>(null);

export function TeamProvider({ children }: { children: ReactNode }) {
  const { active } = useWorkspace();
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    if (!active) {
      setTeams([]);
      return;
    }
    setLoading(true);
    try {
      const list = await api.get<Team[]>(`/workspaces/${active.id}/teams`);
      setTeams(list);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.id]);

  async function join(teamId: string) {
    await api.post(`/teams/${teamId}/join`);
    await refresh();
  }

  async function leave(teamId: string) {
    await api.post(`/teams/${teamId}/leave`);
    await refresh();
  }

  return <TeamContext.Provider value={{ teams, loading, refresh, join, leave }}>{children}</TeamContext.Provider>;
}

export function useTeams(): TeamContextValue {
  const ctx = useContext(TeamContext);
  if (!ctx) throw new Error("useTeams must be used within a TeamProvider");
  return ctx;
}
