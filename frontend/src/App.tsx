import { Route, Routes } from "react-router-dom";

import { Sidebar } from "./components/Sidebar";
import { AdminPage } from "./pages/AdminPage";
import { AssistantPage } from "./pages/AssistantPage";
import { BriefPage } from "./pages/BriefPage";
import { FindingDetailPage } from "./pages/FindingDetailPage";
import { HistoryPage } from "./pages/HistoryPage";
import { SettingsPage } from "./pages/SettingsPage";

export function App() {
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <Sidebar />
      <main className="min-w-0 flex-1 px-4 py-6 pb-16 sm:px-6 md:px-10">
        <Routes>
          <Route path="/" element={<BriefPage />} />
          <Route path="/findings/:id" element={<FindingDetailPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/assistant" element={<AssistantPage />} />
        </Routes>
      </main>
    </div>
  );
}
