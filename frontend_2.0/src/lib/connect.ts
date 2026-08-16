/**
 * Starting an OAuth connection.
 *
 * This cannot be a fetch. Connecting is a full-page browser redirect to the
 * provider's consent screen, and a redirect carries no Authorization header -
 * which is why the backend issues a short-lived, signed "connect ticket" that
 * travels in the URL instead. Same three steps for every provider.
 */

import { api, apiBaseUrl } from "./api";

export type FamilyKey = "google" | "microsoft" | "github" | "slack" | "zoom";

export const FAMILY_LABEL: Record<FamilyKey, string> = {
  google: "Google",
  microsoft: "Microsoft 365",
  github: "GitHub",
  slack: "Slack",
  zoom: "Zoom",
};

/** What connecting this family actually gives you - shown before consent, so
 *  the ask is never a blank "Connect". */
export const FAMILY_BLURB: Record<FamilyKey, string> = {
  google: "Gmail, Calendar and Drive — what arrived, what's scheduled, what changed.",
  microsoft: "Outlook Mail and Calendar, To Do, OneDrive, OneNote and Teams.",
  github: "Repository activity — pull requests, reviews, commits and issues.",
  slack: "Monitored channels — mentions, blockers and whether a channel has gone quiet.",
  zoom: "Meetings, participants and recordings where your plan allows.",
};

/** Which service keys belong to each family, so one grant renders as one card. */
export const FAMILY_SERVICES: Record<FamilyKey, string[]> = {
  google: ["gmail", "google_calendar", "google_drive"],
  microsoft: [
    "microsoft_mail",
    "microsoft_calendar",
    "microsoft_todo",
    "microsoft_onedrive",
    "microsoft_onenote",
    "microsoft_teams",
  ],
  github: ["github"],
  slack: ["slack"],
  zoom: ["zoom"],
};

export const FAMILIES: FamilyKey[] = ["google", "microsoft", "github", "slack", "zoom"];

/**
 * Redirects the browser to the provider's consent screen.
 *
 * `return_to` brings the user back to the page they started from rather than
 * the app root - connecting from a service page and landing on the dashboard
 * is a small thing that makes the product feel like it lost your place.
 */
export async function startConnect(family: FamilyKey, returnTo = "/connections"): Promise<void> {
  const { ticket } = await api.post<{ ticket: string }>(`/integrations/${family}/connect-ticket`);
  const url =
    `${apiBaseUrl}/integrations/${family}/connect` +
    `?ticket=${encodeURIComponent(ticket)}&return_to=${encodeURIComponent(returnTo)}`;
  window.location.href = url;
}
