import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Connection, MailAskResult, MailBody, MailItem } from "../api/types";

type Tab = { key: string; label: string; filter: string; category?: string };

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
  const [expandedId, setExpandedId] = useState<string | null>(null);
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

  async function loadTab(tab: Tab) {
    setLoading(true);
    setAskMessage(null);
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

  async function toggleExpand(item: MailItem) {
    if (expandedId === item.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(item.id);
    if (bodies[item.id]) return;
    setBodies((b) => ({ ...b, [item.id]: "loading" }));
    try {
      const body = await api.get<MailBody>(`/mail/${item.id}/body`);
      setBodies((b) => ({ ...b, [item.id]: body }));
    } catch {
      setBodies((b) => ({ ...b, [item.id]: "error" }));
    }
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
      ) : items.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-8 text-center text-[13px] text-ink-faint">
          Nothing here.
        </div>
      ) : (
        <div className="rounded-md border border-border bg-surface">
          {items.map((item) => (
            <div key={item.id} className="border-b border-border last:border-b-0">
              <button
                onClick={() => toggleExpand(item)}
                className="flex w-full items-start gap-3 p-3.5 text-left hover:bg-surface-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    {item.is_starred && <span className="text-watch">★</span>}
                    <span className={`truncate text-[13px] ${item.is_unread ? "font-semibold text-ink" : "text-ink-dim"}`}>
                      {item.subject}
                    </span>
                  </div>
                  <div className="mt-0.5 truncate text-[11.5px] text-ink-faint">{item.sender}</div>
                </div>
                <div className="flex flex-none items-center gap-1.5">
                  {item.is_important && (
                    <span className="rounded-full border border-crit/40 px-1.5 py-[1px] font-mono text-[9.5px] text-crit">
                      IMPORTANT
                    </span>
                  )}
                  {item.is_spam && (
                    <span className="rounded-full border border-border px-1.5 py-[1px] font-mono text-[9.5px] text-ink-faint">
                      SPAM
                    </span>
                  )}
                  <span className="whitespace-nowrap font-mono text-[11px] text-ink-faint">
                    {new Date(item.occurred_at).toLocaleDateString()}
                  </span>
                </div>
              </button>
              {expandedId === item.id && (
                <div className="border-t border-border bg-ground/50 p-3.5 text-[12.5px] leading-relaxed text-ink-dim">
                  {bodies[item.id] === "loading" && "Fetching live content…"}
                  {bodies[item.id] === "error" && <span className="text-crit">Couldn't fetch this email's content.</span>}
                  {bodies[item.id] && bodies[item.id] !== "loading" && bodies[item.id] !== "error" && (
                    <p className="whitespace-pre-wrap">{(bodies[item.id] as MailBody).body_text ?? "(no readable body)"}</p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
