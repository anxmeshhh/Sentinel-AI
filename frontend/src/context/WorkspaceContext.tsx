import type { ReactNode } from "react";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { api, setActiveWorkspaceId } from "../api/client";
import { useAuth } from "./AuthContext";

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  kind: "personal" | "team" | "organization";
  role: string;
}

interface WorkspaceContextValue {
  workspaces: Workspace[];
  active: Workspace | null;
  setActiveId: (id: string) => void;
  loading: boolean;
  refresh: () => Promise<Workspace[]>;
}

const STORAGE_KEY = "sentinel.activeWorkspaceId";

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeId, setActiveIdState] = useState<string | null>(localStorage.getItem(STORAGE_KEY));
  const [loading, setLoading] = useState(true);

  async function refresh(): Promise<Workspace[]> {
    const list = await api.get<Workspace[]>("/workspaces");
    setWorkspaces(list);
    return list;
  }

  useEffect(() => {
    // GET /workspaces requires auth - wait for AuthProvider to resolve, and
    // only fetch once actually logged in. Logging out clears local state
    // too, so a stale workspace list never briefly shows for the next user.
    if (authLoading) return;
    if (!user) {
      setWorkspaces([]);
      setActiveIdState(null);
      setActiveWorkspaceId(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    refresh()
      .then((list) => {
        const stillValid = list.some((w) => w.id === activeId);
        const initial = stillValid ? activeId! : (list[0]?.id ?? null);
        setActiveIdState(initial);
        setActiveWorkspaceId(initial);
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, authLoading]);

  function setActiveId(id: string) {
    setActiveIdState(id);
    setActiveWorkspaceId(id);
    localStorage.setItem(STORAGE_KEY, id);
  }

  const active = useMemo(() => workspaces.find((w) => w.id === activeId) ?? null, [workspaces, activeId]);

  return (
    <WorkspaceContext.Provider value={{ workspaces, active, setActiveId, loading, refresh }}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within a WorkspaceProvider");
  return ctx;
}
