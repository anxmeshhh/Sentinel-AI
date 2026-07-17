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
    <div className="flex">
      <Sidebar />
      <main className="min-w-0 flex-1 px-8 py-6 pb-16">
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
