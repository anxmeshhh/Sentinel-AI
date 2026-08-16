/**
 * Auth + workspace context.
 *
 * Both are deliberately CLIENT-ONLY. The session is a bearer token in
 * localStorage, which a server render cannot see - so any attempt to render
 * authenticated content on the server would paint a logged-out shell and then
 * flip once hydrated. `useMounted` below is what every authed surface gates on.
 */

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, setActiveWorkspaceId, setAuthToken } from "./api";

const TOKEN_KEY = "sentinel.token";
const WORKSPACE_KEY = "sentinel.workspace";

/* ------------------------------------------------------------------ mounted */

/** True only after the first client render. Guards anything that reads
 *  localStorage or must not be server-rendered. */
export function useMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted;
}

/* --------------------------------------------------------------------- auth */

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  email_verified: boolean;
}

interface TokenResponse {
  access_token: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, name: string, password: string) => Promise<void>;
  requestOtp: (email: string, purpose: "login" | "email_verify") => Promise<void>;
  verifyOtp: (email: string, purpose: "login" | "email_verify", code: string) => Promise<void>;
  loginWithToken: (token: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  async function loadCurrentUser() {
    try {
      setUser(await api.get<AuthUser>("/auth/me"));
    } catch {
      setAuthToken(null);
      localStorage.removeItem(TOKEN_KEY);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (stored) {
      setAuthToken(stored);
      void loadCurrentUser();
    } else {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyToken(token: string) {
    localStorage.setItem(TOKEN_KEY, token);
    setAuthToken(token);
  }

  const value: AuthContextValue = {
    user,
    loading,
    async login(email, password) {
      const { access_token } = await api.post<TokenResponse>("/auth/login", { email, password });
      applyToken(access_token);
      await loadCurrentUser();
    },
    async signup(email, name, password) {
      // No token yet - signup only sends the verification OTP; verifyOtp finishes it.
      await api.post("/auth/signup", { email, name, password });
    },
    async requestOtp(email, purpose) {
      await api.post("/auth/request-otp", { email, purpose });
    },
    async verifyOtp(email, purpose, code) {
      const { access_token } = await api.post<TokenResponse>("/auth/verify-otp", {
        email,
        purpose,
        code,
      });
      applyToken(access_token);
      await loadCurrentUser();
    },
    async loginWithToken(token) {
      applyToken(token);
      await loadCurrentUser();
    },
    logout() {
      localStorage.removeItem(TOKEN_KEY);
      setAuthToken(null);
      setUser(null);
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

/* ---------------------------------------------------------------- workspace */

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  kind: "personal" | "team" | "organization";
  role: string;
  is_demo: boolean;
}

interface WorkspaceContextValue {
  workspaces: Workspace[];
  active: Workspace | null;
  setActiveId: (id: string) => void;
  loading: boolean;
  refresh: () => Promise<Workspace[]>;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeId, setActiveIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Read from localStorage on mount rather than in the initializer: this
  // component can be server-rendered, where localStorage does not exist.
  useEffect(() => {
    setActiveIdState(localStorage.getItem(WORKSPACE_KEY));
  }, []);

  async function refresh(): Promise<Workspace[]> {
    const list = await api.get<Workspace[]>("/workspaces");
    setWorkspaces(list);
    return list;
  }

  useEffect(() => {
    // GET /workspaces requires auth - wait for AuthProvider to resolve, and
    // only fetch once actually logged in. Logging out clears local state too,
    // so a stale workspace list never briefly shows for the next user.
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
      .catch(() => {
        setWorkspaces([]);
        setActiveIdState(null);
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, authLoading]);

  function setActiveId(id: string) {
    setActiveIdState(id);
    setActiveWorkspaceId(id);
    localStorage.setItem(WORKSPACE_KEY, id);
  }

  const active = useMemo(
    () => workspaces.find((w) => w.id === activeId) ?? null,
    [workspaces, activeId],
  );

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
