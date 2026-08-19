import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { DemoWorkspace, OnboardingState, Persona } from "../api/types";
import { useOnboarding } from "../context/OnboardingContext";
import { useWorkspace } from "../context/WorkspaceContext";
import { Button } from "../components/ui";

interface PersonaOption {
  value: Persona;
  icon: string;
  label: string;
  tagline: string;
  focus: string;
}

/** Personas configure one platform - they never fork it. Each option only
 * changes which connections we suggest first and which surfaces get
 * emphasis; every capability stays reachable regardless of choice. */
const PERSONAS: PersonaOption[] = [
  {
    value: "individual",
    icon: "👤",
    label: "Individual / Professional",
    tagline: "A personal command center",
    focus: "Mail, calendar, meetings and documents — what needs you today.",
  },
  {
    value: "developer",
    icon: "⌨️",
    label: "Developer / Technical",
    tagline: "Development intelligence",
    focus: "Pull requests and issues alongside mail, docs and deadlines.",
  },
  {
    value: "team",
    icon: "👥",
    label: "Team / Startup",
    tagline: "Shared channels and context",
    focus: "Group workspaces, channels with shared connections, team briefings.",
  },
  {
    value: "business",
    icon: "🏢",
    label: "Business / Organization",
    tagline: "Operational intelligence",
    focus: "Departments, roles and permissions, cross-team oversight.",
  },
];

export function OnboardingPage() {
  const navigate = useNavigate();
  const { refresh, setActiveId } = useWorkspace();
  // The onboarding gate in RequireAuth reads `onboarded_at` from this
  // context. Saving a persona server-side is not enough - without
  // refreshing here, the gate re-evaluates against stale state, decides the
  // user still hasn't onboarded, and bounces them straight back to this
  // page. That made the app unreachable for every new account.
  const { refresh: refreshOnboarding } = useOnboarding();
  const [selected, setSelected] = useState<Persona | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(persona: Persona) {
    setSelected(persona);
    setBusy(true);
    setError(null);
    try {
      await api.post<OnboardingState>("/onboarding", { persona });
      await refreshOnboarding();
      navigate("/");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save that — try again.");
      setBusy(false);
    }
  }

  async function explore() {
    setSelected("explorer");
    setBusy(true);
    setError(null);
    try {
      await api.post<OnboardingState>("/onboarding", { persona: "explorer" });
      const demo = await api.post<DemoWorkspace>("/onboarding/demo");
      await refreshOnboarding();
      await refresh();
      setActiveId(demo.workspace_id);
      navigate("/");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't start the demo — try again.");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl py-8">
      <h1 className="mb-1.5 text-h1 font-semibold text-balance">How do you work?</h1>
      <p className="mb-7 text-body leading-relaxed text-ink-dim">
        Sentinel brings what matters to you from the tools you already use. This just sets your starting point —
        you can connect anything, change this later, and nothing is hidden permanently.
      </p>

      {error && <p className="mb-4 rounded-md border border-crit/30 bg-crit/10 px-3 py-2 text-small text-crit">{error}</p>}

      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {PERSONAS.map((p) => (
          <button
            key={p.value}
            onClick={() => choose(p.value)}
            disabled={busy}
            className={`rounded-lg border p-4 text-left transition-colors disabled:opacity-60 ${
              selected === p.value ? "border-accent bg-accent/5" : "border-border bg-surface hover:border-accent"
            }`}
          >
            <div className="mb-1.5 text-h2">{p.icon}</div>
            <div className="text-lead font-semibold text-ink">{p.label}</div>
            <div className="mb-1.5 text-caption text-accent-text">{p.tagline}</div>
            <div className="text-small leading-relaxed text-ink-faint">{p.focus}</div>
          </button>
        ))}
      </div>

      <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
        <div className="mb-1 flex items-center gap-2">
          <span className="text-h3">🧭</span>
          <span className="text-lead font-semibold text-ink">Just exploring?</span>
        </div>
        <p className="mb-3 text-small leading-relaxed text-ink-faint">
          Try Sentinel on a realistic sample workspace — mail, calendar, documents and pull requests already in
          place. No accounts to connect, nothing of yours is touched.
        </p>
        <Button size="sm" variant="primary" onClick={explore} disabled={busy}>
          {busy && selected === "explorer" ? "Setting up…" : "Explore Sentinel →"}
        </Button>
      </div>
    </div>
  );
}
