import React from "react";
import ReactDOM from "react-dom/client";

import { LandingPage } from "../src/pages/LandingPage";
import "../src/styles/globals.css";

/**
 * Entry point for the standalone landing build only.
 *
 * No AuthProvider, no workspace, no router - the page reads nothing from the
 * backend, so a static deploy needs none of the application's context tree.
 */
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LandingPage />
  </React.StrictMode>,
);
