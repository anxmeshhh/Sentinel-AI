import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { SentinelAction } from "../api/types";
import { actionLabel } from "./ActionPanel";
import { relativeTime } from "./situations";
import { Action, ActionGroup, Badge, ItemList, ItemRow, type IconName, type Tone } from "./ui";

/**
 * What Sentinel actually did, as its own page section.
 *
 * This is the same GET /actions data ActionPanel's internal history list
 * used to render - moved out to its own persistent section (visible
 * regardless of which tab is active) because that is where the reference
 * design puts it, and because showing it twice - once buried in the Now
 * tab's action composer, once here - would be exactly the duplication the
 * redesign is meant to remove. ActionPanel's `compact` mode hides its own
 * history for that reason.
 *
 * Renders nothing when there is nothing executed yet: an empty "Recent
 * activity" heading is a promise about the future, not a fact about now.
 */
export function RecentActivity({
  scope,
  teamId,
  limit = 5,
}: {
  scope: "personal" | "channel";
  teamId?: string;
  limit?: number;
}) {
  const [actions, setActions] = useState<SentinelAction[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const path = scope === "channel" ? `/teams/${teamId}/actions` : "/actions";

  const load = useCallback(async () => {
    try {
      setActions(await api.get<SentinelAction[]>(path));
    } catch {
      setActions([]);
    }
  }, [path]);

  useEffect(() => {
    void load();
  }, [load]);

  async function undo(id: string) {
    setBusy(id);
    try {
      await api.post(`/actions/${id}/undo`);
      await load();
    } finally {
      setBusy(null);
    }
  }

  const history = (actions ?? []).filter((a) => a.executed_at !== null).slice(0, limit);
  if (history.length === 0) return null;

  return (
    <section className="mb-6">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="text-small font-semibold text-ink">Recent activity</h2>
      </div>
      <ItemList>
        {history.map((a) => {
          const meta = ACTION_META[a.action_type] ?? ACTION_META._default;
          const status = STATUS_COPY[a.status] ?? STATUS_COPY.unknown;
          const canUndo = (a.status === "succeeded" || a.status === "unknown") && !a.undone_at;
          return (
            <ItemRow
              key={a.id}
              tone="neutral"
              icon={meta.icon}
              title={actionLabel(a)}
              source={meta.source}
              meta={[relativeTime(a.executed_at ?? a.created_at)]}
              badge={<Badge tone={a.undone_at ? "watch" : status.tone}>{a.undone_at ? "Undone" : status.label}</Badge>}
              actions={
                canUndo ? (
                  <ActionGroup>
                    <Action kind="undo" loading={busy === a.id} onClick={() => void undo(a.id)} />
                  </ActionGroup>
                ) : undefined
              }
            />
          );
        })}
      </ItemList>
    </section>
  );
}

const STATUS_COPY: Record<string, { label: string; tone: Tone }> = {
  succeeded: { label: "Completed", tone: "good" },
  failed: { label: "Failed", tone: "crit" },
  unknown: { label: "Unconfirmed", tone: "warn" },
};

/** A glyph and a short source name, derived from the real `action_type` key
 *  (e.g. "zoom.create_meeting") - never a separate, inventable field. */
const ACTION_META: Record<string, { icon: IconName; source: string }> = {
  "outlook.mark_read": { icon: "mail", source: "Outlook Mail" },
  "outlook.flag": { icon: "mail", source: "Outlook Mail" },
  "outlook.draft": { icon: "mail", source: "Outlook Mail" },
  "outlook.send": { icon: "mail", source: "Outlook Mail" },
  "outlook.reply_draft": { icon: "mail", source: "Outlook Mail" },
  "outlook.create_event": { icon: "calendar", source: "Outlook Calendar" },
  "outlook.update_event": { icon: "calendar", source: "Outlook Calendar" },
  "outlook.cancel_event": { icon: "calendar", source: "Outlook Calendar" },
  "todo.create_task": { icon: "square", source: "Microsoft To Do" },
  "todo.update_task": { icon: "square", source: "Microsoft To Do" },
  "todo.complete_task": { icon: "square", source: "Microsoft To Do" },
  "todo.delete_task": { icon: "square", source: "Microsoft To Do" },
  "onenote.create_notebook": { icon: "file", source: "OneNote" },
  "onenote.create_section": { icon: "file", source: "OneNote" },
  "onenote.create_page": { icon: "file", source: "OneNote" },
  "onenote.append_page": { icon: "file", source: "OneNote" },
  "onedrive.create_folder": { icon: "file", source: "OneDrive" },
  "onedrive.upload_text": { icon: "file", source: "OneDrive" },
  "onedrive.rename_item": { icon: "file", source: "OneDrive" },
  "onedrive.move_item": { icon: "file", source: "OneDrive" },
  "onedrive.delete_item": { icon: "file", source: "OneDrive" },
  "zoom.create_meeting": { icon: "video", source: "Zoom" },
  "zoom.update_meeting": { icon: "video", source: "Zoom" },
  "zoom.delete_meeting": { icon: "video", source: "Zoom" },
  "commitment.create": { icon: "flag", source: "Commitment" },
  "commitment.resolve": { icon: "flag", source: "Commitment" },
  "goal.create": { icon: "target", source: "Goal" },
  "attention.snooze": { icon: "clock", source: "Reminder" },
  "calendar.create_event": { icon: "calendar", source: "Google Calendar" },
  "email.draft": { icon: "mail", source: "Gmail" },
  "email.send": { icon: "mail", source: "Gmail" },
  "github.create_issue": { icon: "layers", source: "GitHub" },
  _default: { icon: "sparkle", source: "Sentinel" },
};
