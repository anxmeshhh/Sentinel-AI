export type Severity = "critical" | "review" | "reminder";
export type Health =
  | "connected"
  | "syncing"
  | "error"
  | "reconnect"
  | "paused"
  | "needs_setup";

export const severityLabel: Record<Severity, string> = {
  critical: "Critical",
  review: "Review",
  reminder: "Reminder",
};

export const severityColor: Record<Severity, string> = {
  critical: "var(--crit)",
  review: "var(--warn)",
  reminder: "var(--watch)",
};

export const severityRank: Record<Severity, number> = {
  critical: 0,
  review: 1,
  reminder: 2,
};

export type ServiceKey =
  | "gmail"
  | "google_calendar"
  | "google_drive"
  | "github"
  | "slack"
  | "zoom"
  | "microsoft_mail"
  | "microsoft_calendar"
  | "microsoft_todo"
  | "microsoft_onedrive"
  | "microsoft_onenote"
  | "microsoft_teams";

export interface Service {
  key: ServiceKey;
  name: string;
  family: string;
  familyKey: string;
  health: Health;
  account: string;
  syncedMinutesAgo: number;
  listLabel: string;
  detailEmpty: string;
  capability?: { title: string; body: string };
}

export const services: Service[] = [
  {
    key: "gmail",
    name: "Gmail",
    family: "Google",
    familyKey: "google",
    health: "connected",
    account: "animesh@example.com",
    syncedMinutesAgo: 4,
    listLabel: "Messages",
    detailEmpty: "Select a message to read it here.",
  },
  {
    key: "google_calendar",
    name: "Google Calendar",
    family: "Google",
    familyKey: "google",
    health: "connected",
    account: "animesh@example.com",
    syncedMinutesAgo: 4,
    listLabel: "Events",
    detailEmpty: "Select an event to see its details.",
  },
  {
    key: "google_drive",
    name: "Google Drive",
    family: "Google",
    familyKey: "google",
    health: "syncing",
    account: "animesh@example.com",
    syncedMinutesAgo: 1,
    listLabel: "Files",
    detailEmpty: "Select a file to see its details.",
  },
  {
    key: "github",
    name: "GitHub",
    family: "GitHub",
    familyKey: "github",
    health: "connected",
    account: "animeshhh",
    syncedMinutesAgo: 9,
    listLabel: "Repositories",
    detailEmpty: "Select a repository to see its recent work.",
  },
  {
    key: "slack",
    name: "Slack",
    family: "Slack",
    familyKey: "slack",
    health: "connected",
    account: "Acme Corporation",
    syncedMinutesAgo: 6,
    listLabel: "Channels",
    detailEmpty: "Select a channel to see its recent activity.",
  },
  {
    key: "zoom",
    name: "Zoom",
    family: "Zoom",
    familyKey: "zoom",
    health: "connected",
    account: "animesh@example.com",
    syncedMinutesAgo: 4,
    listLabel: "Meetings",
    detailEmpty: "Select a meeting to see its details.",
    capability: {
      title: "About this Zoom account",
      body: "Cloud recordings & transcripts — Cloud recording is part of Zoom's paid plans. This account records locally only, and local recordings never reach Zoom's API, so Sentinel cannot see them.",
    },
  },
  {
    key: "microsoft_mail",
    name: "Outlook Mail",
    family: "Microsoft 365",
    familyKey: "microsoft",
    health: "connected",
    account: "animesh@acme.com",
    syncedMinutesAgo: 4,
    listLabel: "Messages",
    detailEmpty: "Select a message to read it here.",
  },
  {
    key: "microsoft_calendar",
    name: "Outlook Calendar",
    family: "Microsoft 365",
    familyKey: "microsoft",
    health: "connected",
    account: "animesh@acme.com",
    syncedMinutesAgo: 4,
    listLabel: "Events",
    detailEmpty: "Select an event to see its details.",
  },
  {
    key: "microsoft_todo",
    name: "Microsoft To Do",
    family: "Microsoft 365",
    familyKey: "microsoft",
    health: "connected",
    account: "animesh@acme.com",
    syncedMinutesAgo: 7,
    listLabel: "Tasks",
    detailEmpty: "Select a task to see its details.",
  },
  {
    key: "microsoft_onedrive",
    name: "OneDrive",
    family: "Microsoft 365",
    familyKey: "microsoft",
    health: "connected",
    account: "animesh@acme.com",
    syncedMinutesAgo: 22,
    listLabel: "Files",
    detailEmpty: "Select a file to see its details.",
  },
  {
    key: "microsoft_onenote",
    name: "OneNote",
    family: "Microsoft 365",
    familyKey: "microsoft",
    health: "connected",
    account: "animesh@acme.com",
    syncedMinutesAgo: 31,
    listLabel: "Pages",
    detailEmpty: "Select a page to read it here.",
  },
  {
    key: "microsoft_teams",
    name: "Teams",
    family: "Microsoft 365",
    familyKey: "microsoft",
    health: "needs_setup",
    account: "animesh@acme.com",
    syncedMinutesAgo: 0,
    listLabel: "Channels",
    detailEmpty: "Select a channel to see its messages.",
    capability: {
      title: "About Teams on this account",
      body: "Channel messages — Teams requires a Microsoft 365 Business or work/school account. This account does not include it, so Sentinel cannot read Teams channels.",
    },
  },
];

export const healthMeta: Record<
  Health,
  { word: string; color: string }
> = {
  connected: { word: "Connected", color: "var(--good)" },
  syncing: { word: "Syncing", color: "var(--watch)" },
  error: { word: "Sync failing", color: "var(--crit)" },
  reconnect: { word: "Reconnect needed", color: "var(--crit)" },
  paused: { word: "Paused", color: "var(--ink-faint)" },
  needs_setup: { word: "Needs setup", color: "var(--warn)" },
};

export function serviceByKey(key: string): Service | undefined {
  return services.find((s) => s.key === key);
}

export interface Finding {
  id: string;
  severity: Severity;
  status: "open" | "snoozed" | "resolved";
  title: string;
  why: string;
  service: ServiceKey;
  entity: string;
  entityKind: string;
  when: string;
  situationId?: string;
  evidence: { what: string; when: string; link: string }[];
  history: { when: string; what: string }[];
}

export const findings: Finding[] = [
  {
    id: "f-unread-important",
    severity: "critical",
    status: "open",
    title: "3 important messages are still unread",
    why: "Unread and flagged important for over 14 days",
    service: "gmail",
    entity: "animesh@example.com",
    entityKind: "mailbox",
    when: "2d",
    evidence: [
      {
        what: "Contract renewal — Jane Okoro",
        when: "14 Aug 09:12",
        link: "https://mail.google.com",
      },
      {
        what: "Q3 invoice overdue — Billing",
        when: "12 Aug 17:40",
        link: "https://mail.google.com",
      },
      {
        what: "Security review sign-off — Priya N.",
        when: "11 Aug 08:05",
        link: "https://mail.google.com",
      },
    ],
    history: [
      { when: "14 Aug 09:20", what: "Detected" },
      { when: "15 Aug 09:20", what: "Severity raised to Critical" },
    ],
  },
  {
    id: "f-repo-quiet",
    severity: "review",
    status: "open",
    title: "heartbeat-harmony has gone quiet",
    why: "No commits, pull requests or issues for 11 days",
    service: "github",
    entity: "heartbeat-harmony",
    entityKind: "repository",
    when: "11d",
    situationId: "s-heartbeat",
    evidence: [
      {
        what: "Last commit: fix rollback guard",
        when: "04 Aug 13:27",
        link: "https://github.com",
      },
      {
        what: "Open pull request #211 awaiting review",
        when: "03 Aug 10:02",
        link: "https://github.com",
      },
    ],
    history: [{ when: "14 Aug 13:27", what: "Detected" }],
  },
  {
    id: "f-deployment-review",
    severity: "critical",
    status: "open",
    title: "STRESS-TEST: deployment review starts in 3 hours",
    why: "Has a join link and no agenda attached",
    service: "microsoft_calendar",
    entity: "heartbeat-harmony",
    entityKind: "repository",
    when: "3h",
    situationId: "s-heartbeat",
    evidence: [
      {
        what: "Outlook event: STRESS-TEST: deployment review",
        when: "16 Aug 15:00",
        link: "https://outlook.office.com",
      },
    ],
    history: [{ when: "14 Aug 15:27", what: "Detected" }],
  },
  {
    id: "f-rollback-task",
    severity: "review",
    status: "open",
    title: "Rollback task is 4 days overdue",
    why: "Marked important in Microsoft To Do and never completed",
    service: "microsoft_todo",
    entity: "heartbeat-harmony",
    entityKind: "repository",
    when: "4d",
    situationId: "s-heartbeat",
    evidence: [
      {
        what: "Task: Prepare rollback plan for heartbeat-harmony",
        when: "12 Aug 09:00",
        link: "https://to-do.office.com",
      },
    ],
    history: [{ when: "12 Aug 09:05", what: "Detected" }],
  },
  {
    id: "f-zoom-overlap",
    severity: "reminder",
    status: "open",
    title: "Two meetings overlap on Friday afternoon",
    why: "Deploy review and Design sync both start at 15:00",
    service: "zoom",
    entity: "heartbeat-harmony",
    entityKind: "repository",
    when: "1d",
    situationId: "s-heartbeat",
    evidence: [
      {
        what: "Zoom meeting: Deploy review",
        when: "16 Aug 15:00",
        link: "https://zoom.us",
      },
    ],
    history: [{ when: "15 Aug 11:00", what: "Detected" }],
  },
  {
    id: "f-querymind-paused",
    severity: "review",
    status: "open",
    title: "QueryMind has been paused for 3 weeks",
    why: "Deployment workflow disabled and no branch activity since 25 July",
    service: "github",
    entity: "QueryMind",
    entityKind: "repository",
    when: "21d",
    situationId: "s-querymind",
    evidence: [
      {
        what: "Workflow deploy.yml disabled",
        when: "25 Jul 16:11",
        link: "https://github.com",
      },
    ],
    history: [{ when: "01 Aug 08:00", what: "Detected" }],
  },
  {
    id: "f-slack-thread",
    severity: "reminder",
    status: "open",
    title: "A question in #platform has gone unanswered for 5 days",
    why: "You were mentioned directly and nobody replied",
    service: "slack",
    entity: "#platform",
    entityKind: "channel",
    when: "5d",
    evidence: [
      {
        what: "Message from Dan Whitfield",
        when: "11 Aug 14:22",
        link: "https://slack.com",
      },
    ],
    history: [{ when: "11 Aug 14:30", what: "Detected" }],
  },
  {
    id: "f-drive-shared",
    severity: "reminder",
    status: "snoozed",
    title: "A folder is shared with anyone who has the link",
    why: "Contains 14 files last modified this month",
    service: "google_drive",
    entity: "Client handover",
    entityKind: "folder",
    when: "8d",
    evidence: [
      {
        what: "Folder: Client handover",
        when: "08 Aug 10:00",
        link: "https://drive.google.com",
      },
    ],
    history: [
      { when: "08 Aug 10:10", what: "Detected" },
      { when: "09 Aug 08:00", what: "Snoozed for 7 days" },
    ],
  },
  {
    id: "f-onedrive-quota",
    severity: "reminder",
    status: "resolved",
    title: "OneDrive was close to its storage limit",
    why: "Usage dropped back to 71% after older exports were removed",
    service: "microsoft_onedrive",
    entity: "animesh@acme.com",
    entityKind: "drive",
    when: "9d",
    evidence: [
      {
        what: "Storage report",
        when: "07 Aug 06:00",
        link: "https://onedrive.live.com",
      },
    ],
    history: [
      { when: "07 Aug 06:05", what: "Detected" },
      { when: "10 Aug 12:00", what: "Marked done" },
    ],
  },
];

export interface Situation {
  id: string;
  entity: string;
  entityKind: string;
  severity: Severity;
  status: "open" | "resolved";
  openedAgo: string;
  lastActivity: string;
  reasoning: string;
  connectedBecause: string;
  findingIds: string[];
  providers: ServiceKey[];
  recommendations: { id: string; text: string; rationale: string; memory?: boolean }[];
  timeline: { when: string; what: string }[];
  actionsTaken: {
    what: string;
    when: string;
    verification: string;
    undoable: boolean;
  }[];
  memory?: string;
  resolvedAgo?: string;
}

export const situations: Situation[] = [
  {
    id: "s-heartbeat",
    entity: "heartbeat-harmony",
    entityKind: "repository",
    severity: "critical",
    status: "open",
    openedAgo: "2h",
    lastActivity: "18m",
    reasoning:
      "Critical upcoming meetings and an overdue rollback task for the heartbeat-harmony deployment are scheduled across Outlook, Microsoft To Do and Zoom, and the repository itself has shown no commits or reviews for eleven days. The deployment review starts in three hours with no agenda attached and no rollback plan completed.",
    connectedBecause:
      "All four concern the same repository, heartbeat-harmony.",
    findingIds: [
      "f-deployment-review",
      "f-rollback-task",
      "f-repo-quiet",
      "f-zoom-overlap",
    ],
    providers: ["microsoft_calendar", "zoom", "microsoft_todo", "github"],
    recommendations: [
      {
        id: "d-prepare",
        text: "Prepare for the upcoming meeting",
        rationale: "Because this keeps recurring",
        memory: true,
      },
      {
        id: "d-rollback",
        text: "Review the overdue rollback task",
        rationale: "It blocks the deployment review in three hours",
      },
    ],
    timeline: [
      { when: "04 Aug 13:27", what: "Repository went quiet" },
      { when: "12 Aug 09:00", what: "Rollback task became overdue" },
      { when: "14 Aug 15:27", what: "Deployment review scheduled in Outlook" },
      { when: "16 Aug 06:10", what: "Zoom meeting overlap detected" },
    ],
    actionsTaken: [
      {
        what: "Task created in Microsoft To Do",
        when: "12m ago",
        verification:
          "Microsoft To Do has 'Prepare rollback plan' due Fri 16 Aug.",
        undoable: true,
      },
    ],
    memory: "Seen 2 times",
  },
  {
    id: "s-querymind",
    entity: "QueryMind",
    entityKind: "repository",
    severity: "review",
    status: "open",
    openedAgo: "3d",
    lastActivity: "1d",
    reasoning:
      "QueryMind's deployment workflow has been disabled since 25 July and no branch has moved since. Two calendar holds referencing the project were declined, which suggests the work has stalled rather than finished.",
    connectedBecause: "Both concern the same repository, QueryMind.",
    findingIds: ["f-querymind-paused"],
    providers: ["github", "google_calendar"],
    recommendations: [
      {
        id: "d-querymind",
        text: "Decide whether QueryMind is paused on purpose",
        rationale: "Nothing has moved for three weeks",
      },
    ],
    timeline: [
      { when: "25 Jul 16:11", what: "Deployment workflow disabled" },
      { when: "01 Aug 08:00", what: "Repository flagged as paused" },
    ],
    actionsTaken: [],
  },
  {
    id: "s-billing",
    entity: "Acme billing",
    entityKind: "service",
    severity: "review",
    status: "resolved",
    openedAgo: "9d",
    lastActivity: "3d",
    reasoning:
      "An overdue invoice thread in Gmail lined up with a finance review in Google Calendar and a shared folder that had been opened to anyone with the link.",
    connectedBecause: "All three concern the same service, Acme billing.",
    findingIds: ["f-drive-shared"],
    providers: ["gmail", "google_calendar", "google_drive"],
    recommendations: [],
    timeline: [
      { when: "07 Aug 09:00", what: "Invoice thread flagged" },
      { when: "13 Aug 11:30", what: "Invoice marked paid" },
    ],
    actionsTaken: [],
    resolvedAgo: "3 days ago",
  },
];

export function findingById(id: string) {
  return findings.find((f) => f.id === id);
}
export function situationById(id: string) {
  return situations.find((s) => s.id === id);
}
export function situationsForService(key: ServiceKey) {
  return situations.filter((s) => s.providers.includes(key));
}
export function findingsForService(key: ServiceKey) {
  return findings.filter((f) => f.service === key && f.status === "open");
}

export interface Decision {
  id: string;
  text: string;
  rationale: string;
  kind: "recommend" | "inform";
  memoryInformed?: boolean;
  situationId?: string;
}

export const decisions: Decision[] = [
  {
    id: "d-rollback",
    text: "Review the overdue rollback task",
    rationale: "Because this keeps recurring",
    kind: "recommend",
    memoryInformed: true,
    situationId: "s-heartbeat",
  },
  {
    id: "d-prepare",
    text: "Prepare for the deployment review at 15:00",
    rationale: "The meeting has a join link but no agenda",
    kind: "recommend",
    situationId: "s-heartbeat",
  },
  {
    id: "d-drive",
    text: "The Client handover folder is open to anyone with the link",
    rationale: "Nothing to do unless that was unintended",
    kind: "inform",
  },
];

export interface MemoryItem {
  id: string;
  summary: string;
  why: string;
  scope: "personal" | "org";
  scopeName: string;
  firstNoticed: string;
  lastSeen: string;
  evidence: { label: string; situationId: string }[];
  forgotten?: boolean;
  createdHoursAgo: number;
}

export const memories: MemoryItem[] = [
  {
    id: "m-heartbeat",
    summary: '"heartbeat-harmony" keeps recurring — seen 2 times.',
    why: "This situation has formed, resolved and formed again.",
    scope: "personal",
    scopeName: "Personal",
    firstNoticed: "28 Jul",
    lastSeen: "16 Aug",
    evidence: [
      { label: "heartbeat-harmony · 28 Jul", situationId: "s-heartbeat" },
      { label: "heartbeat-harmony · 16 Aug", situationId: "s-heartbeat" },
    ],
    createdHoursAgo: 3,
  },
  {
    id: "m-friday",
    summary: "Friday afternoon meetings are usually rescheduled.",
    why: "Four of the last five Friday meetings moved within a day of starting.",
    scope: "personal",
    scopeName: "Personal",
    firstNoticed: "12 Jul",
    lastSeen: "09 Aug",
    evidence: [{ label: "Acme billing · 09 Aug", situationId: "s-billing" }],
    createdHoursAgo: 96,
  },
  {
    id: "m-forgotten",
    summary: "Invoice threads from Billing get read within a day.",
    why: "Sentinel stopped tracking this pattern when you asked it to forget.",
    scope: "org",
    scopeName: "Acme Corporation",
    firstNoticed: "02 Jul",
    lastSeen: "20 Jul",
    evidence: [],
    forgotten: true,
    createdHoursAgo: 500,
  },
];

export interface AuditRow {
  id: string;
  time: string;
  action: string;
  target: string;
  risk: "low" | "high";
  status: "succeeded" | "unknown" | "failed";
  verification: string;
  who: string;
  undo: "available" | "none" | "used";
}

export const auditRows: AuditRow[] = [
  {
    id: "a-1",
    time: "16 Aug 08:29",
    action: "Create task",
    target: "Prepare rollback plan · Microsoft To Do",
    risk: "low",
    status: "succeeded",
    verification: "Microsoft To Do has the task due Fri 16 Aug.",
    who: "Animesh",
    undo: "available",
  },
  {
    id: "a-2",
    time: "15 Aug 17:02",
    action: "Schedule meeting",
    target: "Deploy review · Zoom",
    risk: "low",
    status: "succeeded",
    verification: "Zoom has 'Deploy review' at Fri 16 Aug 15:00.",
    who: "Animesh",
    undo: "available",
  },
  {
    id: "a-3",
    time: "14 Aug 11:44",
    action: "Send email",
    target: "jane@example.com · Outlook Mail",
    risk: "high",
    status: "succeeded",
    verification: "Outlook reports the message in Sent Items.",
    who: "Animesh",
    undo: "none",
  },
  {
    id: "a-4",
    time: "13 Aug 09:18",
    action: "Update event",
    target: "Design sync · Outlook Calendar",
    risk: "low",
    status: "unknown",
    verification: "Applied, but Sentinel couldn't confirm it.",
    who: "Animesh",
    undo: "available",
  },
  {
    id: "a-5",
    time: "12 Aug 15:55",
    action: "Create folder",
    target: "Handover/2026 · OneDrive",
    risk: "low",
    status: "failed",
    verification: "OneDrive returned: a folder with that name already exists.",
    who: "Animesh",
    undo: "none",
  },
];

export const recentActivity = [
  { what: "Zoom synced", when: "4m ago" },
  { what: "Task created in Microsoft To Do", when: "12m ago" },
  { what: "GitHub synced", when: "9m ago" },
  { what: "Outlook Mail synced", when: "4m ago" },
  { what: "Slack synced", when: "6m ago" },
];

export interface NotificationItem {
  id: string;
  kind: "memory" | "situation" | "critical" | "connection" | "action";
  text: string;
  when: string;
  to: string;
  unread: boolean;
}

export const notifications: NotificationItem[] = [
  {
    id: "n-1",
    kind: "memory",
    text: "Sentinel will remember that heartbeat-harmony keeps recurring.",
    when: "3h ago",
    to: "/memory",
    unread: true,
  },
  {
    id: "n-2",
    kind: "situation",
    text: "A situation formed around heartbeat-harmony.",
    when: "2h ago",
    to: "/situations/s-heartbeat",
    unread: true,
  },
  {
    id: "n-3",
    kind: "critical",
    text: "3 important messages are still unread in Gmail.",
    when: "2d ago",
    to: "/findings/f-unread-important",
    unread: false,
  },
  {
    id: "n-4",
    kind: "connection",
    text: "Teams needs a work or school account before it can be read.",
    when: "4d ago",
    to: "/connections/microsoft",
    unread: false,
  },
  {
    id: "n-5",
    kind: "action",
    text: "Task created in Microsoft To Do.",
    when: "12m ago",
    to: "/history",
    unread: false,
  },
];

export type ContextKind = "personal" | "org" | "class";
export interface WorkContext {
  id: string;
  name: string;
  kind: ContextKind;
  detail: string;
}

export const contexts: WorkContext[] = [
  { id: "personal", name: "Personal", kind: "personal", detail: "Only you can see this" },
  { id: "acme", name: "Acme Corporation", kind: "org", detail: "24 members" },
  { id: "platform", name: "Platform team", kind: "class", detail: "6 members" },
];

export const ctxColor: Record<ContextKind, string> = {
  personal: "var(--ctx-personal)",
  org: "var(--ctx-org)",
  class: "var(--ctx-class)",
};

/* Provider workspace sample content */
export interface WorkItem {
  id: string;
  title: string;
  meta: string;
  sub?: string;
  body: string;
  fields: { label: string; value: string }[];
  actions: string[];
}

const mail = (
  id: string,
  title: string,
  from: string,
  when: string,
  body: string,
): WorkItem => ({
  id,
  title,
  meta: from,
  sub: when,
  body,
  fields: [
    { label: "From", value: from },
    { label: "Received", value: when },
  ],
  actions: ["Mark read", "Flag", "Reply"],
});

export const workContent: Record<ServiceKey, WorkItem[]> = {
  gmail: [
    mail(
      "g1",
      "Contract renewal",
      "Jane Okoro",
      "14 Aug 09:12",
      "Hi Animesh — the renewal window closes at the end of the month. Could you confirm the seat count so I can send the final paperwork?",
    ),
    mail(
      "g2",
      "Q3 invoice overdue",
      "Acme Billing",
      "12 Aug 17:40",
      "Invoice 4471 is now 12 days past due. Payment details are unchanged.",
    ),
    mail(
      "g3",
      "Security review sign-off",
      "Priya Nair",
      "11 Aug 08:05",
      "The security review is complete. One item needs your sign-off before we can close it out.",
    ),
  ],
  google_calendar: [
    {
      id: "gc1",
      title: "Finance review",
      meta: "Thu 15:00 – 15:45",
      body: "Quarterly numbers walkthrough with finance.",
      fields: [
        { label: "When", value: "Thu 15:00 – 15:45" },
        { label: "Attendees", value: "You, Jane Okoro, Dan Whitfield" },
      ],
      actions: ["Create event"],
    },
    {
      id: "gc2",
      title: "1:1 with Priya",
      meta: "Fri 11:00 – 11:30",
      body: "Recurring weekly one to one.",
      fields: [
        { label: "When", value: "Fri 11:00 – 11:30" },
        { label: "Attendees", value: "You, Priya Nair" },
      ],
      actions: ["Create event"],
    },
  ],
  google_drive: [
    {
      id: "gd1",
      title: "Client handover",
      meta: "Folder · 14 files",
      body: "Shared with anyone who has the link.",
      fields: [
        { label: "Type", value: "Folder" },
        { label: "Owner", value: "animesh@example.com" },
      ],
      actions: [],
    },
  ],
  github: [
    {
      id: "gh1",
      title: "heartbeat-harmony",
      meta: "No activity for 11 days",
      body: "Open pull request #211 awaiting review. Last commit: fix rollback guard.",
      fields: [
        { label: "Open PRs", value: "1" },
        { label: "Open issues", value: "4" },
      ],
      actions: [],
    },
    {
      id: "gh2",
      title: "QueryMind",
      meta: "Deployment workflow disabled",
      body: "No branch activity since 25 July.",
      fields: [
        { label: "Open PRs", value: "0" },
        { label: "Open issues", value: "2" },
      ],
      actions: [],
    },
  ],
  slack: [
    {
      id: "sl1",
      title: "#platform",
      meta: "Last message 5 days ago",
      body: "Dan Whitfield mentioned you and nobody replied.",
      fields: [{ label: "Members", value: "18" }],
      actions: [],
    },
  ],
  zoom: [
    {
      id: "z1",
      title: "Deploy review",
      meta: "Fri 16 Aug 15:00",
      body: "Agenda is empty. A join link exists.",
      fields: [
        { label: "Join link", value: "zoom.us/j/98211" },
        { label: "Participants", value: "4 invited" },
      ],
      actions: ["Schedule meeting", "Edit", "Delete"],
    },
    {
      id: "z2",
      title: "Design sync",
      meta: "Fri 16 Aug 15:00",
      body: "Overlaps with Deploy review.",
      fields: [{ label: "Participants", value: "6 invited" }],
      actions: ["Schedule meeting"],
    },
  ],
  microsoft_mail: [
    mail(
      "m1",
      "Deployment postponed?",
      "Jane Okoro",
      "16 Aug 07:41",
      "Are we still going ahead this afternoon? The rollback plan isn't in To Do yet.",
    ),
    mail(
      "m2",
      "Stress test results",
      "Dan Whitfield",
      "15 Aug 18:20",
      "Results attached. Two endpoints degrade above 400 rps.",
    ),
  ],
  microsoft_calendar: [
    {
      id: "mc1",
      title: "STRESS-TEST: deployment review",
      meta: "Fri 16 Aug 15:00 – 16:00",
      body: "No agenda attached. Join link present.",
      fields: [
        { label: "When", value: "Fri 16 Aug 15:00 – 16:00" },
        { label: "Attendees", value: "You, Jane Okoro, Dan Whitfield, Priya Nair" },
      ],
      actions: ["Create event", "Update", "Cancel"],
    },
  ],
  microsoft_todo: [
    {
      id: "mt1",
      title: "Prepare rollback plan for heartbeat-harmony",
      meta: "Due 12 Aug · Important",
      body: "Created by Sentinel 12 minutes ago.",
      fields: [
        { label: "Due", value: "12 Aug" },
        { label: "Importance", value: "High" },
      ],
      actions: ["Create task", "Complete", "Delete"],
    },
  ],
  microsoft_onedrive: [
    {
      id: "od1",
      title: "Handover",
      meta: "Folder · modified 2d ago",
      body: "Contains exports and signed documents.",
      fields: [
        { label: "Size", value: "1.4 GB" },
        { label: "Modified by", value: "Animesh" },
      ],
      actions: ["Create folder", "Rename", "Delete"],
    },
  ],
  microsoft_onenote: [
    {
      id: "on1",
      title: "Deployment runbook",
      meta: "Engineering › Releases",
      body: "Step 1 — freeze the branch. Step 2 — snapshot the database. Step 3 — deploy behind the flag.",
      fields: [{ label: "Section", value: "Releases" }],
      actions: ["Create page", "Append"],
    },
  ],
  microsoft_teams: [],
};

export function greeting(date = new Date()) {
  const h = date.getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}
