import type { ReactNode } from "react";
import { createContext, useContext, useEffect, useState } from "react";

import { api, setAuthToken } from "../api/client";

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

const STORAGE_KEY = "sentinel.token";

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  async function loadCurrentUser() {
    try {
      const me = await api.get<AuthUser>("/auth/me");
      setUser(me);
    } catch {
      setAuthToken(null);
      localStorage.removeItem(STORAGE_KEY);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      setAuthToken(stored);
      loadCurrentUser();
    } else {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyToken(token: string) {
    localStorage.setItem(STORAGE_KEY, token);
    setAuthToken(token);
  }

  async function login(email: string, password: string) {
    const { access_token } = await api.post<TokenResponse>("/auth/login", { email, password });
    applyToken(access_token);
    await loadCurrentUser();
  }

  async function signup(email: string, name: string, password: string) {
    await api.post("/auth/signup", { email, name, password });
    // No token yet - signup only sends the verification OTP; verifyOtp finishes the job.
  }

  async function requestOtp(email: string, purpose: "login" | "email_verify") {
    await api.post("/auth/request-otp", { email, purpose });
  }

  async function verifyOtp(email: string, purpose: "login" | "email_verify", code: string) {
    const { access_token } = await api.post<TokenResponse>("/auth/verify-otp", { email, purpose, code });
    applyToken(access_token);
    await loadCurrentUser();
  }

  async function loginWithToken(token: string) {
    applyToken(token);
    await loadCurrentUser();
  }

  function logout() {
    localStorage.removeItem(STORAGE_KEY);
    setAuthToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, requestOtp, verifyOtp, loginWithToken, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
