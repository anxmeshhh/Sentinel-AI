import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { Sidebar } from "./components/Sidebar";
import { useAuth } from "./context/AuthContext";
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

function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <Sidebar />
      <main className="min-w-0 flex-1 px-4 py-6 pb-16 sm:px-6 md:px-10">{children}</main>
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
      <Route path="/channels/:teamId" element={<RequireAuth><ChannelWorkspacePage /></RequireAuth>} />
    </Routes>
  );
}
