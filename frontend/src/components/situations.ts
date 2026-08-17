/** Shared vocabulary for the Situation surfaces.
 *
 *  Kept in one module because the severity ladder and provider names have to
 *  read identically on the list, the detail page and the dashboard - three
 *  places drifting apart is exactly what makes an app feel like three apps.
 */

/** The one severity ladder, expressed in the app's own Tailwind tokens rather
 *  than raw hex - `crit`/`warn`/`watch` already mean exactly this everywhere
 *  else, and a second colour source would be a second design system. */
export const SEVERITY: Record<string, { label: string; dot: string; text: string; stripe: string }> = {
  critical: { label: "Critical", dot: "bg-crit", text: "text-crit", stripe: "border-l-crit" },
  review: { label: "Review", dot: "bg-warn", text: "text-warn", stripe: "border-l-warn" },
  reminder: { label: "Reminder", dot: "bg-watch", text: "text-watch", stripe: "border-l-watch" },
};

export function severityOf(raw: string | null | undefined) {
  return SEVERITY[raw ?? "review"] ?? SEVERITY["review"]!;
}

/** Provider ids as the API returns them -> what a person calls them. */
export const PROVIDER_LABEL: Record<string, string> = {
  gmail: "Gmail",
  google_calendar: "Google Calendar",
  google_drive: "Google Drive",
  github: "GitHub",
  slack: "Slack",
  zoom: "Zoom",
  microsoft_outlook_mail: "Outlook Mail",
  microsoft_outlook_calendar: "Outlook Calendar",
  microsoft_todo: "Microsoft To Do",
  microsoft_onedrive: "OneDrive",
  microsoft_onenote: "OneNote",
  microsoft_teams: "Teams",
};

/** Where a provider's own workspace page lives, so a Situation can hand the
 *  user straight to the tool the finding came from. */
export const PROVIDER_ROUTE: Record<string, string> = {
  gmail: "/mail",
  google_calendar: "/calendar",
  google_drive: "/drive",
  zoom: "/zoom",
  microsoft_outlook_mail: "/microsoft/mail",
  microsoft_outlook_calendar: "/microsoft/calendar",
  microsoft_todo: "/microsoft/todo",
  microsoft_onedrive: "/microsoft/onedrive",
  microsoft_onenote: "/microsoft/onenote",
};

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });
}

export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
