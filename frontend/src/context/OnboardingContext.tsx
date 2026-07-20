import type { ReactNode } from "react";
import { createContext, useContext, useEffect, useState } from "react";

import { api } from "../api/client";
import type { OnboardingState } from "../api/types";
import { useAuth } from "./AuthContext";

interface OnboardingContextValue {
  state: OnboardingState | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

const OnboardingContext = createContext<OnboardingContextValue | null>(null);

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [state, setState] = useState<OnboardingState | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      setState(await api.get<OnboardingState>("/onboarding"));
    } catch {
      // Never block the app on onboarding state - a failure here should
      // land the user in the product, not in a dead end.
      setState(null);
    }
  }

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      setState(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    refresh().finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, authLoading]);

  return <OnboardingContext.Provider value={{ state, loading, refresh }}>{children}</OnboardingContext.Provider>;
}

export function useOnboarding(): OnboardingContextValue {
  const ctx = useContext(OnboardingContext);
  if (!ctx) throw new Error("useOnboarding must be used within an OnboardingProvider");
  return ctx;
}
