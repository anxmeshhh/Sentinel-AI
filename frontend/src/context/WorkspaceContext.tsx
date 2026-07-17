import type { ReactNode } from "react";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { api, setActiveWorkspaceId } from "../api/client";

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  kind: "personal" | "team" | "organization";
}

interface WorkspaceContextValue {
  workspaces: Workspace[];
  active: Workspace | null;
  setActiveId: (id: string) => void;
  loading: boolean;
}

const STORAGE_KEY = "sentinel.activeWorkspaceId";

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeId, setActiveIdState] = useState<string | null>(localStorage.getItem(STORAGE_KEY));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<Workspace[]>("/workspaces")
      .then((list) => {
        setWorkspaces(list);
        const stillValid = list.some((w) => w.id === activeId);
        const initial = stillValid ? activeId! : (list[0]?.id ?? null);
        setActiveIdState(initial);
        setActiveWorkspaceId(initial);
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setActiveId(id: string) {
    setActiveIdState(id);
    setActiveWorkspaceId(id);
    localStorage.setItem(STORAGE_KEY, id);
  }

  const active = useMemo(() => workspaces.find((w) => w.id === activeId) ?? null, [workspaces, activeId]);

  return (
    <WorkspaceContext.Provider value={{ workspaces, active, setActiveId, loading }}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within a WorkspaceProvider");
  return ctx;
}
