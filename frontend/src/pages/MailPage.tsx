import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Connection, MailAskResult, MailBody, MailItem } from "../api/types";

type Tab = { key: string; label: string; filter: string; category?: string };

interface ThreadGroup {
  key: string;
  messages: MailItem[]; // sorted newest-first
}

const TABS: Tab[] = [
  { key: "recent", label: "Recent", filter: "recent" },
  { key: "top", label: "Top 10", filter: "top" },
  { key: "starred", label: "Starred", filter: "starred" },
  { key: "important", label: "Important", filter: "important" },
  { key: "unread", label: "Unread", filter: "unread" },
  { key: "spam", label: "Spam", filter: "spam" },
  { key: "promotions", label: "Promotions", filter: "category", category: "promotions" },
  { key: "social", label: "Social", filter: "category", category: "social" },
  { key: "updates", label: "Updates", filter: "category", category: "updates" },
];

export function MailPage() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>(TABS[0]);
  const [items, setItems] = useState<MailItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [askInput, setAskInput] = useState("");
  const [askMessage, setAskMessage] = useState<string | null>(null);
  const [expandedThread, setExpandedThread] = useState<string | null>(null);
  const [expandedMessageId, setExpandedMessageId] = useState<string | null>(null);
  const [bodies, setBodies] = useState<Record<string, MailBody | "loading" | "error">>({});

  useEffect(() => {
    api.get<Connection[]>("/connections").then((conns) => {
      setConnected(conns.some((c) => c.provider === "gmail"));
    });
  }, []);

  useEffect(() => {
    if (connected === false) {
      setLoading(false);
      return;
    }
    loadTab(activeTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, connected]);

  // Gmail groups multiple messages in the same conversation under one row
  // with a count badge - thread_id was already captured at ingestion but
  // never surfaced. Same grouping here, client-side, off the flat list.
  const threads = useMemo<ThreadGroup[]>(() => {
    const byKey = new Map<string, MailItem[]>();
    for (const item of items) {
      const key = item.thread_id ?? item.id;
      const list = byKey.get(key) ?? [];
      list.push(item);
      byKey.set(key, list);
    }
    const groups = Array.from(byKey.entries()).map(([key, messages]) => ({
      key,
      messages: [...messages].sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at)),
    }));
    groups.sort((a, b) => Date.parse(b.messages[0].occurred_at) - Date.parse(a.messages[0].occurred_at));
    return groups;
  }, [items]);

  async function loadTab(tab: Tab) {
    setLoading(true);
    setAskMessage(null);
    setExpandedThread(null);
    setExpandedMessageId(null);
    try {
      const qs = new URLSearchParams({ filter: tab.filter, limit: "30" });
      if (tab.category) qs.set("category", tab.category);
      const data = await api.get<MailItem[]>(`/mail?${qs.toString()}`);
      setItems(data);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  async function handleAsk() {
    const question = askInput.trim();
    if (!question) return;
    setLoading(true);
    setAskMessage(null);
    try {
      const result = await api.post<MailAskResult>("/mail/ask", { question });
      if (result.matched_filter) {
        setItems(result.items);
        setActiveTab({ key: "ask", label: `"${question}"`, filter: result.matched_filter, category: result.matched_category ?? undefined });
      } else {
        setItems([]);
        setAskMessage(result.message);
      }
    } finally {
      setLoading(false);
    }
  }

  async function fetchBody(item: MailItem) {
    if (bodies[item.id]) return;
    setBodies((b) => ({ ...b, [item.id]: "loading" }));
    try {
      const body = await api.get<MailBody>(`/mail/${item.id}/body`);
      setBodies((b) => ({ ...b, [item.id]: body }));
    } catch {
      setBodies((b) => ({ ...b, [item.id]: "error" }));
    }
  }

  function toggleThread(group: ThreadGroup) {
    if (expandedThread === group.key) {
      setExpandedThread(null);
      return;
    }
    setExpandedThread(group.key);
    // A single-message "thread" behaves like before: one click shows its body.
    // A real multi-message thread expands to a message list first.
    if (group.messages.length === 1) {
      setExpandedMessageId(group.messages[0].id);
      void fetchBody(group.messages[0]);
    }
  }

  function toggleMessage(item: MailItem) {
    if (expandedMessageId === item.id) {
      setExpandedMessageId(null);
      return;
    }
    setExpandedMessageId(item.id);
    void fetchBody(item);
  }

  function renderBody(id: string) {
    const state = bodies[id];
    if (state === "loading") return <p className="p-3.5 text-[12.5px] text-ink-dim">Fetching live content&hellip;</p>;
    if (state === "error") return <p className="p-3.5 text-[12.5px] text-crit">Couldn't fetch this email's content.</p>;
    if (!state) return null;
    return <p className="whitespace-pre-wrap p-3.5 text-[12.5px] leading-relaxed text-ink-dim">{state.body_text ?? "(no readable body)"}</p>;
  }

  if (connected === false) {
    return (
      <div className="max-w-lg rounded-md border border-dashed border-border p-10 text-center text-ink-dim">
        <p className="mb-3 text-[14px]">Gmail isn't connected yet.</p>
        <Link to="/settings" className="font-mono text-[13px] font-semibold text-accent-text hover:underline">
          Connect Gmail &rarr;
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      <h1 className="mb-1 text-xl font-semibold text-balance">Mail</h1>
      <p className="mb-6 text-[13px] text-ink-dim">
        Subject, sender, and labels only — full content is fetched live when you open an email, never stored.
      </p>

      <div className="mb-5 flex gap-2">
        <input
          value={askInput}
          onChange={(e) => setAskInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAsk()}
          placeholder="Ask: what's in starred, show me spam, top 10…"
          className="flex-1 rounded-md border border-border bg-surface px-3.5 py-2.5 text-[13px] outline-none focus:border-accent"
        />
        <button
          onClick={handleAsk}
          className="rounded-md border border-border bg-surface px-4 py-2.5 text-[12.5px] font-semibold text-ink-dim hover:border-accent hover:text-ink"
        >
          Ask
        </button>
      </div>

      <div className="mb-5 flex flex-wrap gap-1.5">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab)}
            className={`rounded-full border px-3 py-1.5 font-mono text-[11.5px] transition-colors ${
              activeTab.key === tab.key
                ? "border-accent bg-accent/15 text-accent-text"
                : "border-border text-ink-faint hover:text-ink"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {askMessage && <p className="mb-4 text-[12.5px] text-watch">{askMessage}</p>}

      {loading ? (
        <div className="text-ink-dim">Loading&hellip;</div>
      ) : threads.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-8 text-center text-[13px] text-ink-faint">
          Nothing here.
        </div>
      ) : (
        <div className="rounded-md border border-border bg-surface">
          {threads.map((group) => {
            const latest = group.messages[0];
            const isUnread = group.messages.some((m) => m.is_unread);
            return (
              <div key={group.key} className="border-b border-border last:border-b-0">
                <button
                  onClick={() => toggleThread(group)}
                  className="flex w-full items-start gap-3 p-3.5 text-left hover:bg-surface-2"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      {latest.is_starred && <span className="text-watch">★</span>}
                      <span className={`truncate text-[12px] ${isUnread ? "font-semibold text-ink" : "text-ink-faint"}`}>
                        {latest.sender}
                      </span>
                      {group.messages.length > 1 && (
                        <span className="flex-none rounded-full bg-surface-2 px-1.5 py-[1px] font-mono text-[10px] text-ink-dim">
                          {group.messages.length}
                        </span>
                      )}
                    </div>
                    <div className={`mt-0.5 truncate text-[13px] ${isUnread ? "font-semibold text-ink" : "text-ink-dim"}`}>
                      {latest.subject}
                    </div>
                  </div>
                  <div className="flex flex-none items-center gap-1.5">
                    {latest.is_important && (
                      <span className="rounded-full border border-crit/40 px-1.5 py-[1px] font-mono text-[9.5px] text-crit">
                        IMPORTANT
                      </span>
                    )}
                    {latest.is_spam && (
                      <span className="rounded-full border border-border px-1.5 py-[1px] font-mono text-[9.5px] text-ink-faint">
                        SPAM
                      </span>
                    )}
                    <span className="whitespace-nowrap font-mono text-[11px] text-ink-faint">
                      {new Date(latest.occurred_at).toLocaleDateString()}
                    </span>
                  </div>
                </button>

                {expandedThread === group.key && (
                  <div className="border-t border-border bg-ground/50">
                    {group.messages.length === 1
                      ? renderBody(latest.id)
                      : group.messages.map((m) => (
                          <div key={m.id} className="border-b border-border/60 last:border-b-0">
                            <button
                              onClick={() => toggleMessage(m)}
                              className="flex w-full items-center justify-between gap-3 py-2 pl-8 pr-3.5 text-left hover:bg-surface-2/50"
                            >
                              <span className={`truncate text-[12px] ${m.is_unread ? "font-semibold text-ink" : "text-ink-faint"}`}>
                                {m.subject}
                              </span>
                              <span className="flex-none font-mono text-[10.5px] text-ink-faint">
                                {new Date(m.occurred_at).toLocaleString()}
                              </span>
                            </button>
                            {expandedMessageId === m.id && renderBody(m.id)}
                          </div>
                        ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
