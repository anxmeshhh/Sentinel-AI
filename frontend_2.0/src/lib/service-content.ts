/**
 * The read surface behind each Provider Workspace.
 *
 * Every service normalizes into one `WorkItem` shape, which is what lets a
 * single page render twelve products. The differences that remain are the ones
 * that are actually real - a mailbox has a sender, a meeting has a join link -
 * and they live in `fields`, not in a per-provider layout.
 *
 * Services with no list endpoint yet are declared honestly rather than faked:
 * `supported: false` makes the page say so instead of rendering an empty list
 * that looks like "you have nothing".
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "./api";
import { useWorkspace } from "./auth";
import type { ServiceKey, WorkItem } from "./sentinel-data";
import { ago } from "./sentinel-live";

interface Surface {
  path: string;
  /** Raw provider rows -> the one shape the workspace page renders. */
  map: (rows: any) => WorkItem[];
}

const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";

const SURFACES: Partial<Record<ServiceKey, Surface>> = {
  gmail: {
    path: "/mail?limit=50",
    map: (rows: any[]) =>
      (rows ?? []).map((m) => ({
        id: String(m.id),
        title: m.subject || "(no subject)",
        meta: m.from ?? "",
        sub: when(m.occurred_at),
        body: m.snippet ?? "",
        fields: [
          { label: "From", value: m.from ?? "—" },
          { label: "Received", value: when(m.occurred_at) },
          { label: "State", value: m.unread ? "Unread" : "Read" },
        ],
        actions: [],
      })),
  },
  microsoft_mail: {
    path: "/workspace/microsoft/mail?limit=50",
    map: (rows: any[]) =>
      (rows ?? []).map((m) => ({
        id: String(m.id),
        title: m.subject || "(no subject)",
        meta: m.from ?? "",
        sub: when(m.occurred_at),
        body: "",
        fields: [
          { label: "From", value: m.from ?? "—" },
          { label: "To", value: m.to ?? "—" },
          { label: "Received", value: when(m.occurred_at) },
          { label: "State", value: m.unread ? "Unread" : "Read" },
        ],
        actions: ["outlook.mark_read", "outlook.flag", "outlook.reply_draft"],
      })),
  },
  google_calendar: {
    path: "/calendar",
    map: (rows: any) =>
      (rows?.events ?? rows ?? []).map((e: any) => ({
        id: String(e.id ?? e.external_id),
        title: e.title || e.summary || "(untitled)",
        meta: when(e.start),
        sub: e.organizer ?? "",
        body: "",
        fields: [
          { label: "Starts", value: when(e.start) },
          { label: "Ends", value: when(e.end) },
          { label: "Attendees", value: String(e.attendee_count ?? "—") },
        ],
        actions: [],
      })),
  },
  microsoft_calendar: {
    path: "/workspace/microsoft/calendar",
    map: (rows: any[]) =>
      (rows ?? []).map((e) => ({
        id: String(e.id ?? e.event_id),
        title: e.title || "(untitled)",
        meta: when(e.start),
        sub: e.organizer ?? "",
        body: "",
        fields: [
          { label: "Starts", value: when(e.start) },
          { label: "Ends", value: when(e.end) },
          { label: "Attendees", value: String(e.attendee_count ?? "—") },
        ],
        actions: ["outlook.update_event", "outlook.cancel_event"],
      })),
  },
  microsoft_todo: {
    path: "/workspace/microsoft/todo",
    map: (rows: any) =>
      (rows?.tasks ?? rows ?? []).map((t: any) => ({
        id: String(t.id ?? t.task_id),
        title: t.title || "(untitled task)",
        meta: t.due_at ? `Due ${when(t.due_at)}` : "No due date",
        sub: t.list ?? "",
        body: t.body ?? "",
        fields: [
          { label: "List", value: t.list ?? "—" },
          { label: "Due", value: t.due_at ? when(t.due_at) : "—" },
          { label: "Importance", value: t.importance ?? "normal" },
          { label: "Status", value: t.completed ? "Completed" : "Open" },
        ],
        actions: ["todo.complete_task", "todo.update_task", "todo.delete_task"],
      })),
  },
  microsoft_onedrive: {
    path: "/workspace/microsoft/onedrive",
    map: (rows: any) =>
      (rows?.items ?? []).map((f: any) => ({
        id: String(f.id),
        title: f.name,
        meta: f.is_folder ? "Folder" : f.mime_type || "File",
        sub: when(f.modified_at),
        body: "",
        fields: [
          { label: "Type", value: f.is_folder ? "Folder" : (f.mime_type ?? "File") },
          { label: "Modified", value: when(f.modified_at) },
          { label: "Changed by", value: f.modified_by ?? "—" },
        ],
        actions: ["onedrive.rename_item", "onedrive.delete_item"],
      })),
  },
  microsoft_onenote: {
    path: "/workspace/microsoft/onenote",
    map: (rows: any) =>
      (rows?.pages ?? []).map((p: any) => ({
        id: String(p.id),
        title: p.title || "(untitled page)",
        meta: when(p.modified_at),
        sub: "",
        body: "",
        fields: [{ label: "Modified", value: when(p.modified_at) }],
        actions: ["onenote.append_page"],
      })),
  },
  zoom: {
    path: "/workspace/zoom/meetings?filter=upcoming",
    map: (rows: any[]) =>
      (rows ?? []).map((m) => ({
        id: String(m.meeting_id),
        title: m.topic || "(no topic)",
        meta: when(m.start),
        sub: m.host ?? "",
        body: "",
        fields: [
          { label: "Starts", value: when(m.start) },
          { label: "Host", value: m.host ?? "—" },
          { label: "Join", value: m.join_url ?? "—" },
        ],
        actions: ["zoom.update_meeting", "zoom.delete_meeting"],
      })),
  },
};

/** Services with no list endpoint yet. Named so the UI can say what is missing
 *  rather than showing an empty list, which reads as "you have nothing". */
export const UNSUPPORTED_REASON: Partial<Record<ServiceKey, string>> = {
  github: "Sentinel watches your repositories for activity, but does not browse them here yet.",
  slack: "Sentinel watches monitored channels for activity, but does not browse messages here yet.",
  microsoft_teams: "Teams needs a work or school account with a Teams licence.",
  google_drive: "Drive is searched live rather than browsed - use search to find a file.",
};

export function useServiceContent(service: ServiceKey | undefined) {
  const { active, loading } = useWorkspace();
  const surface = service ? SURFACES[service] : undefined;

  const query = useQuery({
    queryKey: ["service-content", active?.id, service],
    enabled: Boolean(surface) && !loading && Boolean(active),
    queryFn: async (): Promise<WorkItem[]> => {
      const raw = await api.get<any>(surface!.path);
      return surface!.map(raw);
    },
  });

  return {
    ...query,
    supported: Boolean(surface),
    unsupportedReason: service ? UNSUPPORTED_REASON[service] : undefined,
  };
}

export { ago };
