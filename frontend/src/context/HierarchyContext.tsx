import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { api } from "../api/client";
import type { TreeClass } from "../api/types";
import { useWorkspace } from "./WorkspaceContext";

interface HierarchyContextValue {
  tree: TreeClass[];
  loading: boolean;
  refresh: () => Promise<void>;
}

const HierarchyContext = createContext<HierarchyContextValue | null>(null);

/**
 * The Workspace -> Class -> Group -> Channel tree for the active workspace.
 *
 * One request rather than three nested ones: the sidebar needs the whole
 * shape to render at all, and fetching it per level would make expanding a
 * class a loading state instead of an instant toggle.
 *
 * Personal workspaces have no tree by design (no classes, no groups, no
 * channels - see services/hierarchy.py), so the fetch is skipped rather
 * than firing a request guaranteed to return [].
 */
export function HierarchyProvider({ children }: { children: ReactNode }) {
  const { active } = useWorkspace();
  const [tree, setTree] = useState<TreeClass[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!active || active.kind === "personal") {
      setTree([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      setTree(await api.get<TreeClass[]>(`/workspaces/${active.id}/tree`));
    } catch {
      setTree([]);
    } finally {
      setLoading(false);
    }
  }, [active]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return <HierarchyContext.Provider value={{ tree, loading, refresh }}>{children}</HierarchyContext.Provider>;
}

export function useHierarchy(): HierarchyContextValue {
  const ctx = useContext(HierarchyContext);
  if (!ctx) throw new Error("useHierarchy must be used within a HierarchyProvider");
  return ctx;
}
