import type { ReactNode } from "react";
import { useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AssistantFab } from "./components/assistant/AssistantFab";
import { CreateWorkspaceModal } from "./components/CreateWorkspaceModal";
import { MemoryToast } from "./components/MemoryToast";
import { Sidebar } from "./components/Sidebar";
import { useAuth } from "./context/AuthContext";
import { useWorkspace } from "./context/WorkspaceContext";
import { useOnboarding } from "./context/OnboardingContext";
import { AdminPage } from "./pages/AdminPage";
import { AssistantPage } from "./pages/AssistantPage";
import { AttentionPage } from "./pages/AttentionPage";
import { ActionAuditPage } from "./pages/ActionAuditPage";
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
import { MicrosoftTodoPage } from "./pages/MicrosoftTodoPage";
import { OneDrivePage } from "./pages/OneDrivePage";
import { OneNotePage } from "./pages/OneNotePage";
import { ZoomPage } from "./pages/ZoomPage";
import { OutlookCalendarPage } from "./pages/OutlookCalendarPage";
import { OutlookMailPage } from "./pages/OutlookMailPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SituationDetailPage } from "./pages/SituationDetailPage";
import { SituationsPage } from "./pages/SituationsPage";
import { MemoryPage } from "./pages/MemoryPage";
import { GoalsPage } from "./pages/GoalsPage";
import { FindingsPage } from "./pages/FindingsPage";
import { SignupPage } from "./pages/SignupPage";
import { Icon, LoadingBlock } from "./components/ui";

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
  const [collapsed, setCollapsed] = useState(false);
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const { refresh, setActiveId } = useWorkspace();
  const { pathname } = useLocation();

  return (
    <div className="flex h-screen overflow-hidden bg-ground">
      {/* One navigation column. It was two - a 56px icon rail beside a 248px
          tree - which is the main reason the shell never read as a single
          application. Everything the rail did lives in the sidebar now. */}
      {mobileNavOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/70 md:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden="true"
        />
      )}
      <div
        className={`fixed inset-y-0 left-0 z-50 border-r border-rule transition-all duration-200 md:static md:z-auto md:translate-x-0 ${
          collapsed ? "w-[64px]" : "w-[212px]"
        } ${mobileNavOpen ? "translate-x-0" : "-translate-x-full"}`}
      >
        <Sidebar
          collapsed={collapsed}
          onToggle={() => setCollapsed((v) => !v)}
          onOpenCreate={() => setCreatingWorkspace(true)}
        />
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <button
          onClick={() => setMobileNavOpen(true)}
          className="flex flex-none items-center gap-2 border-b border-rule bg-surface px-4 py-3 text-small text-ink-dim md:hidden"
        >
          <Icon name="menu" size={16} />
          Navigate
        </button>
        <main className="min-w-0 flex-1 overflow-y-auto px-4 py-6 pb-16 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-[1400px]">{children}</div>
        </main>
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
      <MemoryToast />

      {/* One entry point to the one Assistant, mounted here so every
          authenticated route gets it for free rather than each page wiring
          its own. Hidden on /assistant itself - a button that navigates to
          the page you are already on is not a shortcut, it is a decoy. */}
      {pathname !== "/assistant" && <AssistantFab />}
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const { state: onboarding, loading: onboardingLoading } = useOnboarding();

  if (loading || onboardingLoading) {
    return <div className="flex min-h-screen items-center justify-center"><LoadingBlock /></div>;
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
    return <div className="flex min-h-screen items-center justify-center"><LoadingBlock /></div>;
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
      <Route path="/situations" element={<RequireAuth><SituationsPage /></RequireAuth>} />
      {/* Both of these were linked from the dashboard, the rail and the
          Assistant but had no route - every "View memory" 404'd. */}
      <Route path="/findings" element={<RequireAuth><FindingsPage /></RequireAuth>} />
      <Route path="/memory" element={<RequireAuth><MemoryPage /></RequireAuth>} />
      <Route path="/goals" element={<RequireAuth><GoalsPage /></RequireAuth>} />
      <Route path="/situations/:id" element={<RequireAuth><SituationDetailPage /></RequireAuth>} />
      <Route path="/audit/actions" element={<RequireAuth><ActionAuditPage /></RequireAuth>} />
      <Route path="/findings/:id" element={<RequireAuth><FindingDetailPage /></RequireAuth>} />
      <Route path="/history" element={<RequireAuth><HistoryPage /></RequireAuth>} />
      <Route path="/settings" element={<RequireAuth><SettingsPage /></RequireAuth>} />
      <Route path="/admin" element={<RequireAuth><AdminPage /></RequireAuth>} />
      <Route path="/assistant" element={<RequireAuth><AssistantPage /></RequireAuth>} />
      <Route path="/mail" element={<RequireAuth><MailPage /></RequireAuth>} />
      <Route path="/microsoft/mail" element={<RequireAuth><OutlookMailPage /></RequireAuth>} />
      <Route path="/microsoft/calendar" element={<RequireAuth><OutlookCalendarPage /></RequireAuth>} />
      <Route path="/microsoft/todo" element={<RequireAuth><MicrosoftTodoPage /></RequireAuth>} />
      <Route path="/microsoft/onedrive" element={<RequireAuth><OneDrivePage /></RequireAuth>} />
      <Route path="/microsoft/onenote" element={<RequireAuth><OneNotePage /></RequireAuth>} />
      <Route path="/zoom" element={<RequireAuth><ZoomPage /></RequireAuth>} />
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
