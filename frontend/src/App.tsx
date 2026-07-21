import type { ReactNode } from "react";
import { useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { CreateWorkspaceModal } from "./components/CreateWorkspaceModal";
import { HierarchyTree } from "./components/HierarchyTree";
import { WorkspaceRail } from "./components/WorkspaceRail";
import { useAuth } from "./context/AuthContext";
import { useWorkspace } from "./context/WorkspaceContext";
import { useOnboarding } from "./context/OnboardingContext";
import { AdminPage } from "./pages/AdminPage";
import { AssistantPage } from "./pages/AssistantPage";
import { AttentionPage } from "./pages/AttentionPage";
import { BriefPage } from "./pages/BriefPage";
import { CalendarPage } from "./pages/CalendarPage";
import { ChannelWorkspacePage } from "./pages/ChannelWorkspacePage";
import { ConnectionWorkspacePage } from "./pages/ConnectionWorkspacePage";
import { DrivePage } from "./pages/DrivePage";
import { FindingDetailPage } from "./pages/FindingDetailPage";
import { HistoryPage } from "./pages/HistoryPage";
import { JoinInvitePage } from "./pages/JoinInvitePage";
import { LoginPage } from "./pages/LoginPage";
import { MailPage } from "./pages/MailPage";
import { MeetPage } from "./pages/MeetPage";
import { OAuthCallbackPage } from "./pages/OAuthCallbackPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SignupPage } from "./pages/SignupPage";

/**
 * Three panes, one per level of the hierarchy question:
 *
 *   [rail]        which workspace am I in?      (context switcher)
 *   [tree]        where in it?                  (Class > Group > Channel)
 *   [work area]   what am I doing here?         (the module)
 *
 * Kept separate on purpose. The previous single sidebar mixed workspace
 * switching, channel listing and workspace-level nav in one column, which
 * is exactly the "one cluttered surface for four levels" this replaces.
 */
function AppShell({ children }: { children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const { refresh, setActiveId } = useWorkspace();

  return (
    <div className="flex h-screen overflow-hidden">
      <div className="hidden md:block">
        <WorkspaceRail onOpenCreate={() => setCreatingWorkspace(true)} />
      </div>

      {/* Navigation pane: a drawer below md, a fixed column above it. */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-40 bg-black/70 md:hidden" onClick={() => setMobileNavOpen(false)} aria-hidden="true" />
      )}
      <div
        className={`fixed inset-y-0 left-0 z-50 flex w-[260px] transition-transform duration-200 md:static md:z-auto md:translate-x-0 ${
          mobileNavOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="md:hidden">
          <WorkspaceRail onOpenCreate={() => setCreatingWorkspace(true)} />
        </div>
        <div className="min-w-0 flex-1 border-r border-border bg-surface">
          <HierarchyTree />
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <button
          onClick={() => setMobileNavOpen(true)}
          className="flex flex-none items-center gap-2 border-b border-border bg-surface px-4 py-3 text-[12.5px] text-ink-dim md:hidden"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M1 4h14M1 8h14M1 12h14" stroke="currentColor" strokeWidth="1.4" />
          </svg>
          Navigate
        </button>
        <main className="min-w-0 flex-1 overflow-y-auto px-4 py-6 pb-16 sm:px-6 md:px-8">{children}</main>
      </div>

      {creatingWorkspace && (
        <CreateWorkspaceModal
          onClose={() => setCreatingWorkspace(false)}
          onCreated={async (w) => {
            // Refresh before switching - `active` resolves by finding the id
            // in the cached list, so pointing at one that isn't there yet
            // resolves to null and strands the dashboard on its loader.
            await refresh();
            setActiveId(w.id);
          }}
        />
      )}
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const { state: onboarding, loading: onboardingLoading } = useOnboarding();

  if (loading || onboardingLoading) {
    return <div className="flex min-h-screen items-center justify-center text-[13px] text-ink-dim">Loading&hellip;</div>;
  }
  if (!user) return <Navigate to="/login" replace />;
  // First run: pick how you work before landing in the product. If the
  // onboarding fetch failed entirely (state === null) we let them through
  // rather than trapping them behind a broken gate.
  if (onboarding && !onboarding.onboarded_at) return <Navigate to="/onboarding" replace />;
  return <AppShell>{children}</AppShell>;
}

/** The persona picker itself is auth-gated but deliberately outside
 * AppShell - no sidebar to navigate away from a first-run choice. */
function OnboardingRoute() {
  const { user, loading } = useAuth();
  if (loading) {
    return <div className="flex min-h-screen items-center justify-center text-[13px] text-ink-dim">Loading&hellip;</div>;
  }
  if (!user) return <Navigate to="/login" replace />;
  return (
    <div className="min-h-screen px-4 sm:px-6">
      <OnboardingPage />
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/auth/callback" element={<OAuthCallbackPage />} />
      <Route path="/invite/:token" element={<JoinInvitePage />} />
      <Route path="/onboarding" element={<OnboardingRoute />} />

      <Route path="/" element={<RequireAuth><BriefPage /></RequireAuth>} />
      <Route path="/attention" element={<RequireAuth><AttentionPage /></RequireAuth>} />
      <Route path="/findings/:id" element={<RequireAuth><FindingDetailPage /></RequireAuth>} />
      <Route path="/history" element={<RequireAuth><HistoryPage /></RequireAuth>} />
      <Route path="/settings" element={<RequireAuth><SettingsPage /></RequireAuth>} />
      <Route path="/admin" element={<RequireAuth><AdminPage /></RequireAuth>} />
      <Route path="/assistant" element={<RequireAuth><AssistantPage /></RequireAuth>} />
      <Route path="/mail" element={<RequireAuth><MailPage /></RequireAuth>} />
      <Route path="/calendar" element={<RequireAuth><CalendarPage /></RequireAuth>} />
      <Route path="/drive" element={<RequireAuth><DrivePage /></RequireAuth>} />
      <Route path="/meet" element={<RequireAuth><MeetPage /></RequireAuth>} />
      <Route path="/connections/:provider" element={<RequireAuth><ConnectionWorkspacePage /></RequireAuth>} />
      {/* Channel modules are separate destinations, not tabs on one loaded
          dashboard - `:module` drives which one mounts, so nothing but the
          chosen module ever fetches. */}
      <Route path="/channels/:teamId" element={<RequireAuth><ChannelWorkspacePage /></RequireAuth>} />
      <Route path="/channels/:teamId/:module" element={<RequireAuth><ChannelWorkspacePage /></RequireAuth>} />
    </Routes>
  );
}
