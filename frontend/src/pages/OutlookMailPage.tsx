import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { OutlookMailBody, OutlookMailItem } from "../api/types";
import { MailIcon } from "../components/ProviderIcons";
import { ActionButton, ProviderWorkspace } from "../components/workspace/ProviderWorkspace";
import { Button, Icon, LoadingBlock } from "../components/ui";

const FILTERS = [
  { key: "recent", label: "All" },
  { key: "unread", label: "Unread" },
  { key: "flagged", label: "Flagged" },
  { key: "important", label: "Important" },
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

/**
 * Outlook Mail as a workspace, not a dashboard: read the real mailbox, open a
 * message, and act on it without leaving Sentinel.
 *
 * Every write goes through <ActionButton>, which proposes an Action Registry
 * action and executes it only after the server's own preview is confirmed.
 * This page never calls Microsoft Graph - it cannot, and that is the point.
 */
export function OutlookMailPage() {
  const [items, setItems] = useState<OutlookMailItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [notConnected, setNotConnected] = useState(false);
  const [filter, setFilter] = useState<FilterKey>("recent");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<OutlookMailItem | null>(null);
  const [body, setBody] = useState<OutlookMailBody | "loading" | { error: string } | null>(null);
  const [composing, setComposing] = useState(false);
  const [replying, setReplying] = useState(false);
  // Bumped after any successful write so the list, the reader and the
  // intelligence rail all reflect the change Microsoft just accepted.
  const [refreshKey, setRefreshKey] = useState(0);

  const load = useCallback(() => {
    setLoading(true);
    const qs = new URLSearchParams({ filter });
    if (query.trim()) qs.set("q", query.trim());
    api
      .get<OutlookMailItem[]>(`/workspace/microsoft/mail?${qs.toString()}`)
      .then((rows) => {
        setItems(rows);
        setNotConnected(false);
      })
      .catch(() => setNotConnected(true))
      .finally(() => setLoading(false));
  }, [filter, query]);

  useEffect(load, [load, refreshKey]);

  function openMessage(item: OutlookMailItem) {
    setSelected(item);
    setReplying(false);
    setBody("loading");
    api
      .get<OutlookMailBody>(`/workspace/microsoft/mail/${item.id}/body`)
      .then(setBody)
      .catch((e) => setBody({ error: e instanceof Error ? e.message : "Couldn't open that message" }));
  }

  function afterWrite() {
    setRefreshKey((k) => k + 1);
    if (selected) {
      // Re-read the message so read/flag state shown here matches Outlook.
      api
        .get<OutlookMailBody>(`/workspace/microsoft/mail/${selected.id}/body`)
        .then(setBody)
        .catch(() => undefined);
    }
  }

  return (
    <ProviderWorkspace
      service="microsoft_mail"
      title="Outlook Mail"
      icon={<MailIcon />}
      parent={{ label: "Microsoft 365", to: "/connections/microsoft" }}
      refreshKey={refreshKey}
      assistant={{
        contextLabel: "Microsoft 365",
        endpointBase: "/connections/microsoft",
        placeholder: "Ask about your mail…",
      }}
      quickActions={
        <Button size="sm" variant="primary" onClick={() => setComposing((v) => !v)}>
          {composing ? "Close" : "New draft"}
        </Button>
      }
    >
      {composing && <Composer onDone={() => { setComposing(false); afterWrite(); }} />}

      {notConnected ? (
        <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
          Outlook Mail isn't connected yet.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          {/* ---- list ---- */}
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  onClick={() => setFilter(f.key)}
                  className={`rounded-md px-2.5 py-1 text-caption transition-colors ${
                    filter === f.key
                      ? "bg-surface-2 font-semibold text-ink"
                      : "text-ink-faint hover:text-ink"
                  }`}
                >
                  {f.label}
                </button>
              ))}
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search subject or sender…"
                className="ml-auto min-w-[10rem] flex-1 rounded-md border border-border bg-surface px-2.5 py-1 text-caption text-ink placeholder:text-ink-faint"
              />
            </div>

            {loading ? (
              <LoadingBlock />
            ) : items.length === 0 ? (
              <div className="rounded-md border border-dashed border-border px-4 py-10 text-center text-caption text-ink-faint">
                Nothing here. If this looks wrong, the mailbox may not have synced yet.
              </div>
            ) : (
              <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
                {items.map((m) => (
                  <li key={m.id}>
                    <button
                      onClick={() => openMessage(m)}
                      className={`flex w-full flex-col gap-0.5 px-3 py-2.5 text-left transition-colors hover:bg-surface/60 ${
                        selected?.id === m.id ? "bg-surface/70" : ""
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {m.unread && <span className="h-1.5 w-1.5 flex-none rounded-full bg-brand" aria-label="Unread" />}
                        <span className={`min-w-0 flex-1 truncate text-small ${m.unread ? "font-semibold text-ink" : "text-ink-dim"}`}>
                          {m.subject}
                        </span>
                        {m.flagged && <span className="flex-none text-caption text-warn">Flagged</span>}
                      </div>
                      <div className="flex items-center gap-2 text-caption text-ink-faint">
                        <span className="min-w-0 flex-1 truncate">{m.from}</span>
                        {m.occurred_at && (
                          <span className="flex-none">
                            {new Date(m.occurred_at).toLocaleDateString([], { day: "numeric", month: "short" })}
                          </span>
                        )}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* ---- reader + actions ---- */}
          <div className="min-w-0">
            {!selected ? (
              <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-caption text-ink-faint">
                Select a message to read it here.
              </div>
            ) : (
              <div className="card">
                <h2 className="text-lead font-semibold leading-tight text-ink text-balance">{selected.subject}</h2>
                <div className="mt-1 text-caption text-ink-faint">
                  {selected.from}
                  {selected.to ? ` → ${selected.to}` : ""}
                </div>

                {/* Every one of these is an Action Registry proposal. */}
                <div className="mt-3 flex flex-wrap items-center gap-2 border-y border-border py-2.5">
                  <ActionButton
                    actionType="outlook.mark_read"
                    params={{
                      message_id: selected.message_id,
                      is_read: !(typeof body === "object" && body && "is_read" in body ? body.is_read : !selected.unread),
                      subject: selected.subject,
                    }}
                    label={
                      (typeof body === "object" && body && "is_read" in body ? body.is_read : !selected.unread)
                        ? "Mark unread"
                        : "Mark read"
                    }
                    undoable
                    onDone={afterWrite}
                  />
                  <ActionButton
                    actionType="outlook.flag"
                    params={{
                      message_id: selected.message_id,
                      flagged: !(typeof body === "object" && body && "flagged" in body ? body.flagged : selected.flagged),
                      subject: selected.subject,
                    }}
                    label={
                      (typeof body === "object" && body && "flagged" in body ? body.flagged : selected.flagged)
                        ? "Clear flag"
                        : "Flag"
                    }
                    undoable
                    onDone={afterWrite}
                  />
                  <Button size="sm" onClick={() => setReplying((v) => !v)}>
                    {replying ? "Cancel reply" : "Reply"}
                  </Button>
                  {selected.url && (
                    <a
                      href={selected.url}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-auto inline-flex items-center gap-1 text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
                    >
                      Open in Outlook <Icon name="external" size={12} />
                    </a>
                  )}
                </div>

                {replying && (
                  <ReplyBox
                    messageId={selected.message_id}
                    subject={selected.subject}
                    onDone={() => { setReplying(false); afterWrite(); }}
                  />
                )}

                <div className="mt-3">
                  {body === "loading" ? (
                    <LoadingBlock />
                  ) : body && "error" in body ? (
                    <p className="text-caption text-crit">{body.error}</p>
                  ) : body ? (
                    <p className="whitespace-pre-wrap text-small leading-relaxed text-ink-dim">{body.body_text}</p>
                  ) : null}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </ProviderWorkspace>
  );
}

/** Compose a real Outlook draft. Nothing is sent - sending has no inverse, so
 *  it stays out of the allow-list; the draft lands in Outlook to send there. */
function Composer({ onDone }: { onDone: () => void }) {
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [text, setText] = useState("");
  const recipients = to.split(",").map((s) => s.trim()).filter(Boolean);
  const ready = recipients.length > 0 && subject.trim().length > 0 && text.trim().length > 0;

  return (
    <div className="card mb-4">
      <div className="mb-2 text-small font-semibold text-ink">New draft</div>
      <div className="flex flex-col gap-2">
        <input
          value={to}
          onChange={(e) => setTo(e.target.value)}
          placeholder="To (comma-separated)"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="Subject"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          placeholder="Write your message…"
          className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
        />
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            actionType="outlook.draft"
            params={{ to: recipients, subject, body: text }}
            label="Save as draft"
            confirmLabel="Create draft"
            undoable
            disabled={!ready}
            onDone={onDone}
          />
          {/* Sending is irreversible, so it gets its own explicit review step -
              see ActionButton's high-risk branch, which shows the recipients,
              subject and full message before anything leaves the mailbox. */}
          <ActionButton
            actionType="outlook.send"
            params={{ to: recipients, subject, body: text }}
            label="Send"
            variant="primary"
            disabled={!ready}
            onDone={onDone}
          />
          <span className="text-caption text-ink-faint">
            Drafts are undoable. Sending is reviewed first and cannot be undone.
          </span>
        </div>
      </div>
    </div>
  );
}

function ReplyBox({ messageId, subject, onDone }: { messageId: string; subject: string; onDone: () => void }) {
  const [text, setText] = useState("");
  return (
    <div className="mt-3 rounded-md border border-border p-3">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder="Write your reply…"
        className="w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-caption text-ink placeholder:text-ink-faint"
      />
      <div className="mt-2 flex items-center gap-2">
        <ActionButton
          actionType="outlook.reply_draft"
          params={{ message_id: messageId, body: text, subject }}
          label="Save reply draft"
          confirmLabel="Create reply draft"
          variant="primary"
          undoable
          disabled={text.trim().length === 0}
          onDone={onDone}
        />
        <span className="text-caption text-ink-faint">Drafted on the thread in Outlook.</span>
      </div>
    </div>
  );
}
