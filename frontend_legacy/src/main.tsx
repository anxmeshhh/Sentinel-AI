import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { AuthProvider } from "./context/AuthContext";
import { OnboardingProvider } from "./context/OnboardingContext";
import { HierarchyProvider } from "./context/HierarchyContext";
import { ToastProvider } from "./components/ui";
import { TeamProvider } from "./context/TeamContext";
import { WorkspaceProvider } from "./context/WorkspaceContext";
import "./styles/globals.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <OnboardingProvider>
          <WorkspaceProvider>
            <TeamProvider>
              <HierarchyProvider>
                <ToastProvider>
                  <App />
                </ToastProvider>
              </HierarchyProvider>
            </TeamProvider>
          </WorkspaceProvider>
        </OnboardingProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
