import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { Connection, MailAskResult, MailBody, MailItem, MailSummary } from "../api/types";
import { MailIcon } from "../components/ProviderIcons";
import { Markdown } from "../components/Markdown";
import { GOOGLE_ASSISTANT } from "../components/workspace/assistantConfigs";
import { ProviderWorkspace } from "../components/workspace/ProviderWorkspace";
import { Button, Icon, LoadingBlock, PageHeader } from "../components/ui";

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
  // Freshness: "Recent" must reflect the current mailbox, so the page pulls new
  // mail on open (and on demand) rather than trusting the coarse background poll.
  const [refreshing, setRefreshing] = useState(false);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  const didAutoRefresh = useRef(false);

  const [selectedThreadKey, setSelectedThreadKey] = useState<string | null>(null);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [mobileReaderOpen, setMobileReaderOpen] = useState(false);

  // The error side of these unions carries the backend's actual `detail`
  // message - a stale email (deleted from Gmail since the last sync) now
  // returns a specific 410 explanation, which is far more useful than the
  // old generic "couldn't fetch" (or, before that, a mystery CORS error).
  const [bodies, setBodies] = useState<Record<string, MailBody | "loading" | { error: string }>>({});
  const [summaries, setSummaries] = useState<Record<string, MailSummary | "loading" | { error: string }>>({});
  const [summaryOpen, setSummaryOpen] = useState<Record<string, boolean>>({});

  useEffect(() => {
    api
      .get<Connection[]>("/connections")
      .then((conns) => setConnected(conns.some((c) => c.provider === "gmail")))
      // See CalendarPage: an unhandled rejection here leaves `connected`
      // null and the page stuck in its loading state.
      .catch(() => setConnected(false));
  }, []);

  useEffect(() => {
    if (connected === false) {
      setLoading(false);
      return;
    }
    loadTab(activeTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, connected]);

  // On first open, pull the newest mail so "Recent" is genuinely current - the
  // cached list shows instantly, then this refreshes it. Incremental, so cheap.
  useEffect(() => {
    if (connected && !didAutoRefresh.current) {
      didAutoRefresh.current = true;
      void refresh();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected]);

  async function refresh() {
    setRefreshing(true);
    try {
      const res = await api.post<{ synced: number; last_synced_at: string | null }>("/mail/refresh");
      setSyncedAt(res.last_synced_at);
      await loadTab(activeTab);
    } catch {
      // Best-effort: the cached list still shows if the refresh can't reach Gmail.
    } finally {
      setRefreshing(false);
    }
  }

  // Gmail groups multiple messages in the same conversation under one row
  // with a count badge - same grouping here, off the flat list.
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

  const selectedGroup = threads.find((t) => t.key === selectedThreadKey) ?? null;
  const selectedItem = selectedGroup?.messages.find((m) => m.id === selectedMessageId) ?? null;

  async function loadTab(tab: Tab) {
    setLoading(true);
    setAskMessage(null);
    setSelectedThreadKey(null);
    setSelectedMessageId(null);
    setMobileReaderOpen(false);
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
    } catch (e) {
      setBodies((b) => ({ ...b, [item.id]: { error: e instanceof ApiError ? e.message : "Couldn't fetch this email's content." } }));
    }
  }

  async function fetchSummary(item: MailItem) {
    const existing = summaries[item.id];
    if (existing && !(typeof existing === "object" && "error" in existing)) {
      setSummaryOpen((o) => ({ ...o, [item.id]: true }));
      return;
    }
    setSummaries((s) => ({ ...s, [item.id]: "loading" }));
    try {
      const summary = await api.get<MailSummary>(`/mail/${item.id}/summary`);
      setSummaries((s) => ({ ...s, [item.id]: summary }));
      setSummaryOpen((o) => ({ ...o, [item.id]: true }));
    } catch (e) {
      setSummaries((s) => ({ ...s, [item.id]: { error: e instanceof ApiError ? e.message : "Couldn't generate a summary — try again." } }));
    }
  }

  function selectThread(group: ThreadGroup) {
    setSelectedThreadKey(group.key);
    setMobileReaderOpen(true);
    const first = group.messages[0];
    setSelectedMessageId(first.id);
    void fetchBody(first);
  }

  function selectMessage(item: MailItem) {
    setSelectedMessageId(item.id);
    void fetchBody(item);
  }

  if (connected === false) {
    return (
      <ProviderWorkspace
        service="gmail"
        title="Gmail"
        icon={<MailIcon />}
        parent={{ label: "Google Workspace", to: "/connections/google" }}
      >
        <div className="max-w-lg rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">
          <p className="mb-3 text-lead">Gmail isn't connected yet.</p>
          <Link to="/settings" className="text-body font-semibold text-accent-text hover:underline">
            Connect Gmail &rarr;
          </Link>
        </div>
      </ProviderWorkspace>
    );
  }

  return (
    <ProviderWorkspace
      service="gmail"
      title="Gmail"
      icon={<MailIcon />}
      parent={{ label: "Google Workspace", to: "/connections/google" }}
      assistant={GOOGLE_ASSISTANT}
      activitySources={["Gmail"]}
    >
      <PageHeader
        eyebrow="Personal"
        title="Mail"
        description="Click an email to read it — original content only, no AI call. Summarize is optional, on demand."
        actions={connected ? (
          <div className="flex flex-none items-center gap-2 pt-1">
            <span className="text-micro text-ink-faint">
              {refreshing ? "Refreshing…" : syncedAt ? `Synced ${new Date(syncedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : ""}
            </span>
            <Button size="sm" variant="secondary" onClick={() => void refresh()} disabled={refreshing}>
              <Icon name="refresh" size={13} /> Refresh
            </Button>
          </div>
        ) : undefined}
      />

      <div className="flex gap-4" style={{ height: "calc(100vh - 12rem)" }}>
        <div className={`w-full flex-none overflow-y-auto lg:block lg:w-[360px] ${mobileReaderOpen ? "hidden" : "block"}`}>
          <div className="mb-3 flex gap-2">
            <input
              value={askInput}
              onChange={(e) => setAskInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAsk()}
              placeholder="Ask: what's in starred, top 10…"
              className="flex-1 rounded-md border border-border bg-transparent px-3 py-2.5 text-small text-ink transition-colors duration-200 placeholder:text-ink-faint outline-none focus:border-border-strong focus:ring-2 focus:ring-ink/10 disabled:cursor-not-allowed disabled:opacity-50"
            />
            <Button variant="secondary" size="sm"
              onClick={handleAsk}
              
            >
              Ask
            </Button>
          </div>

          <div className="mb-3 flex flex-wrap gap-1.5">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab)}
                className={`rounded-full border px-2.5 py-1 font-mono text-caption transition-colors ${
                  activeTab.key === tab.key
                    ? "border-accent bg-accent/15 text-accent-text"
                    : "border-border text-ink-faint hover:text-ink"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {askMessage && <p className="mb-3 text-small text-watch">{askMessage}</p>}

          {loading ? (
            <LoadingBlock />
          ) : threads.length === 0 ? (
            <div className="rounded-md border border-dashed border-border px-5 py-8 text-center text-caption text-ink-faint">
              Nothing here.
            </div>
          ) : (
            <div className="card">
              {threads.map((group) => {
                const latest = group.messages[0];
                const isUnread = group.messages.some((m) => m.is_unread);
                const isSelected = group.key === selectedThreadKey;
                return (
                  <button
                    key={group.key}
                    onClick={() => selectThread(group)}
                    className={`flex w-full items-start gap-2 border-b border-border p-3 text-left last:border-b-0 ${
                      isSelected ? "bg-accent/10" : "hover:bg-surface-2"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        {latest.is_starred && <span className="text-watch">★</span>}
                        <span className={`truncate text-caption ${isUnread ? "font-semibold text-ink" : "text-ink-faint"}`}>
                          {latest.sender}
                        </span>
                        {group.messages.length > 1 && (
                          <span className="flex-none rounded-full bg-surface-2 px-1.5 py-[1px] text-micro text-ink-dim">
                            {group.messages.length}
                          </span>
                        )}
                      </div>
                      <div className={`mt-0.5 truncate text-small ${isUnread ? "font-semibold text-ink" : "text-ink-dim"}`}>
                        {latest.subject}
                      </div>
                      <div className="mt-0.5 text-caption text-ink-faint">
                        {new Date(latest.occurred_at).toLocaleDateString()}
                      </div>
                    </div>
                    {latest.is_important && <span className="flex-none text-crit">!</span>}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className={`min-w-0 flex-1 overflow-y-auto card lg:block ${mobileReaderOpen ? "block" : "hidden"}`}>
          {!selectedGroup || !selectedItem ? (
            <div className="flex h-full items-center justify-center p-8 text-center text-body text-ink-faint">
              Select an email to read it.
            </div>
          ) : (
            <EmailReader
              group={selectedGroup}
              selected={selectedItem}
              onSelectMessage={selectMessage}
              bodyState={bodies[selectedItem.id]}
              summaryState={summaries[selectedItem.id]}
              summaryIsOpen={Boolean(summaryOpen[selectedItem.id])}
              onSummarize={() => fetchSummary(selectedItem)}
              onToggleSummary={() => setSummaryOpen((o) => ({ ...o, [selectedItem.id]: !o[selectedItem.id] }))}
              onBack={() => setMobileReaderOpen(false)}
            />
          )}
        </div>
      </div>
    </ProviderWorkspace>
  );
}

function EmailReader({
  group,
  selected,
  onSelectMessage,
  bodyState,
  summaryState,
  summaryIsOpen,
  onSummarize,
  onToggleSummary,
  onBack,
}: {
  group: ThreadGroup;
  selected: MailItem;
  onSelectMessage: (item: MailItem) => void;
  bodyState: MailBody | "loading" | { error: string } | undefined;
  summaryState: MailSummary | "loading" | { error: string } | undefined;
  summaryIsOpen: boolean;
  onSummarize: () => void;
  onToggleSummary: () => void;
  onBack: () => void;
}) {
  const summarizing = summaryState === "loading";

  return (
    <div>
      <button onClick={onBack} className="border-b border-border px-4 py-2.5 text-caption text-ink-faint hover:text-ink lg:hidden">
        &larr; Back to list
      </button>

      {group.messages.length > 1 && (
        <div className="flex gap-1.5 overflow-x-auto border-b border-border p-2.5">
          {group.messages.map((m) => (
            <button
              key={m.id}
              onClick={() => onSelectMessage(m)}
              className={`flex-none whitespace-nowrap rounded-full border px-2.5 py-1 font-mono text-caption ${
                m.id === selected.id ? "border-accent bg-accent/15 text-accent-text" : "border-border text-ink-faint hover:text-ink"
              }`}
            >
              {new Date(m.occurred_at).toLocaleDateString()}
            </button>
          ))}
        </div>
      )}

      <div className="p-4">
        <div className="mb-3 flex items-start justify-between gap-3 border-b border-border pb-3">
          <div className="min-w-0">
            <div className="text-sub font-semibold text-ink">{selected.subject}</div>
            <div className="mt-1 text-small text-ink-faint">
              <span className="text-ink-dim">From:</span> {selected.sender}
            </div>
            <div className="mt-0.5 text-caption text-ink-faint">{new Date(selected.occurred_at).toLocaleString()}</div>
          </div>
          <div className="flex flex-none flex-col items-end gap-1.5">
            <a
              href={selected.url}
              target="_blank"
              rel="noopener noreferrer"
              className="whitespace-nowrap text-caption text-ink-faint underline underline-offset-2 hover:text-ink"
            >
              Open in Gmail
            </a>
            <Button size="sm" variant="primary" onClick={onSummarize} disabled={summarizing}>
              {summarizing ? "Summarizing…" : "Summarize ✨"}
            </Button>
          </div>
        </div>

        {summaryState && !(typeof summaryState === "object" && "error" in summaryState) && (
          <div className="mb-4 rounded-md border border-brand/25 bg-brand/[0.05] p-4 shadow-card">
            <button
              onClick={onToggleSummary}
              className="label-sub flex w-full items-center justify-between px-3 py-2 text-left font-bold text-accent-text"
            >
              <span>AI Summary ✨</span>
              <span className={`transition-transform ${summaryIsOpen ? "rotate-180" : ""}`}>&#9660;</span>
            </button>
            {summaryIsOpen && summaryState !== "loading" && (
              <div className="border-t border-accent/20 px-3 py-3 text-small leading-relaxed text-ink-dim">
                <p className="mb-3">{summaryState.summary}</p>
                {summaryState.key_points.length > 0 && (
                  <>
                    <div className="label-sub mb-1 font-bold text-ink-dim">Key Points</div>
                    <ul className="mb-3 list-disc space-y-1 pl-4">
                      {summaryState.key_points.map((p, i) => (
                        <li key={i}>{p}</li>
                      ))}
                    </ul>
                  </>
                )}
                {summaryState.action_items.length > 0 && (
                  <>
                    <div className="label-sub mb-1 font-bold text-watch">Action Items</div>
                    <ul className="list-disc space-y-1 pl-4 text-ink">
                      {summaryState.action_items.map((a, i) => (
                        <li key={i}>{a}</li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}
          </div>
        )}
        {typeof summaryState === "object" && "error" in summaryState && (
          <p className="mb-4 text-small text-crit">{summaryState.error}</p>
        )}

        <div className="label-sub font-bold">Original Email</div>
        <div className="mt-2 text-body leading-relaxed text-ink-dim">
          {bodyState === "loading" && "Fetching…"}
          {typeof bodyState === "object" && "error" in bodyState && <span className="text-crit">{bodyState.error}</span>}
          {bodyState && bodyState !== "loading" && !("error" in bodyState) && (
            <Markdown text={bodyState.body_text ?? "(no readable body)"} />
          )}
        </div>
      </div>
    </div>
  );
}
