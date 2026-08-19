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

/**
 * Compact due/starts wording.
 *
 * "Was due 1d ago in Tasks — marked high importance" is a sentence; this
 * produces the "1 day overdue" half of `Tasks · 1 day overdue`, and the row
 * supplies the rest as separate facts. Overdue reads as overdue rather than as
 * a negative interval, because that is the thing a person is scanning for.
 */
export function dueLabel(
  iso: string | null | undefined,
  /** Meetings start and have started; tasks are due and go overdue. Same
   *  arithmetic, different noun - saying a meeting is "overdue" reads as a
   *  bug to anyone who was in it. */
  verb: "due" | "meeting" = "due",
): string | null {
  if (!iso) return null;
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  const overdue = mins < 0;
  const abs = Math.abs(mins);

  const amount =
    abs < 60
      ? `${abs}m`
      : abs < 60 * 24
        ? `${Math.round(abs / 60)}h`
        : `${Math.round(abs / (60 * 24))} day${Math.round(abs / (60 * 24)) === 1 ? "" : "s"}`;

  if (overdue) return verb === "meeting" ? `started ${amount} ago` : `${amount} overdue`;
  if (abs < 60 * 24) return `in ${amount}`;
  return `due ${new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" })}`;
}

/** What kind of thing this is, in a word. The row already shows which service
 *  it came from, so this says the noun, not the sentence. */
export const ATTENTION_KIND_LABEL: Record<string, string> = {
  important_email: "Email",
  upcoming_meeting: "Meeting",
  stale_pr: "Pull request",
  finding: "Finding",
  manual: "Reminder",
  deadline: "Deadline",
  conversation_mention: "Mention",
  conversation_blocker: "Blocker",
  conversation_urgent: "Urgent",
};

/**
 * Priority -> the shared severity ladder.
 *
 * Lives here rather than on a page so the Command Center and /attention can
 * never disagree about how serious the same row is - they were each deriving
 * it independently before.
 */
export function attentionTier(item: { origin: string; priority: number }): string {
  if (item.origin === "manual") return "reminder";
  if (item.priority >= 0.8) return "critical";
  if (item.priority >= 0.5) return "review";
  return "reminder";
}

/** Severity -> the design system's Tone, so severity colour is chosen in one
 *  place rather than re-derived as class strings on every page. */
export const TONE: Record<string, "crit" | "warn" | "watch" | "neutral"> = {
  critical: "crit",
  review: "warn",
  reminder: "watch",
};

/**
 * The compact facts for one attention row.
 *
 * Three surfaces render the same row - Command Center, Attention, Assistant -
 * and each was assembling this list itself. The third copy is how one of them
 * ended up telling people a meeting was "16h overdue" while the other two said
 * "started 16h ago". One function, one wording.
 */
export function attentionMeta(item: {
  type: string;
  due_at: string | null;
}): (string | null)[] {
  return [
    ATTENTION_KIND_LABEL[item.type] ?? null,
    dueLabel(item.due_at, item.type === "upcoming_meeting" ? "meeting" : "due"),
  ];
}

/**
 * The four-step priority scale, with its badge.
 *
 * The severity ladder (critical/review/reminder) drives the situation colours,
 * but attention rows need the spec's Critical/High/Medium/Low - and "review"
 * was collapsing High and Medium into one amber step. This derives all four
 * from the engine's own `priority` float; nothing here invents a ranking.
 */
export function priorityOf(item: { origin: string; priority: number }): {
  label: string;
  tone: "crit" | "high" | "warn" | "info";
} {
  if (item.origin === "manual") return { label: "Low", tone: "info" };
  if (item.priority >= 0.8) return { label: "Critical", tone: "crit" };
  if (item.priority >= 0.65) return { label: "High", tone: "high" };
  if (item.priority >= 0.5) return { label: "Medium", tone: "warn" };
  return { label: "Low", tone: "info" };
}

/** What kind of thing a row is, as a glyph - so the row reads as a task, a
 *  meeting or a message before any of its words are read. */
export const ATTENTION_ICON: Record<string, string> = {
  important_email: "mail",
  upcoming_meeting: "calendar",
  stale_pr: "layers",
  finding: "alert",
  manual: "square",
  deadline: "clock",
  conversation_mention: "hash",
  conversation_blocker: "alert",
  conversation_urgent: "alert",
};
