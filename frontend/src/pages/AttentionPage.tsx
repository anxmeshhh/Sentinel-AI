import type { FormEvent } from "react";
import { useEffect, useState } from "react";

import { api, ApiError } from "../api/client";
import type { AttentionItem } from "../api/types";
import { attentionIcon, EvidenceLink } from "../components/AttentionStrip";
import { BackNav } from "../components/BackNav";
import { GoogleAICommand } from "../components/GoogleAICommand";

const STATE_FILTERS = [
  { key: "new", label: "Open" },
  { key: "snoozed", label: "Snoozed" },
  { key: "done", label: "Done" },
  { key: "dismissed", label: "Dismissed" },
];

const SNOOZE_OPTIONS = [
  { label: "3 hours", hours: 3 },
  { label: "Tomorrow", hours: 24 },
  { label: "Next week", hours: 24 * 7 },
];

export function AttentionPage() {
  const [stateFilter, setStateFilter] = useState("new");
  const [items, setItems] = useState<AttentionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [snoozeMenuFor, setSnoozeMenuFor] = useState<string | null>(null);
  const [askItem, setAskItem] = useState<AttentionItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [newTitle, setNewTitle] = useState("");
  const [newDue, setNewDue] = useState("");

  async function load(filter = stateFilter) {
    setLoading(true);
    try {
      setItems(await api.get<AttentionItem[]>(`/attention?state=${filter}`));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load(stateFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stateFilter]);

  async function setState(item: AttentionItem, state: string, snoozeHours?: number) {
    setSnoozeMenuFor(null);
    setItems((list) => list.filter((i) => i.id !== item.id));
    try {
      await api.patch(`/attention/${item.id}`, {
        state,
        ...(snoozeHours ? { snoozed_until: new Date(Date.now() + snoozeHours * 3600 * 1000).toISOString() } : {}),
      });
    } catch {
      setItems((list) => [item, ...list]);
    }
  }

  async function refresh() {
    setRefreshing(true);
    try {
      await api.post<AttentionItem[]>("/attention/refresh");
      await load();
    } finally {
      setRefreshing(false);
    }
  }

  async function addReminder(e: FormEvent) {
    e.preventDefault();
    if (!newTitle.trim()) return;
    await api.post("/attention", {
      title: newTitle.trim(),
      due_at: newDue ? new Date(newDue).toISOString() : null,
    });
    setNewTitle("");
    setNewDue("");
    if (stateFilter === "new") await load();
  }

  return (
    <div className="max-w-5xl">
      <BackNav back={{ to: "/", label: "Dashboard" }} />
      <div className="mb-1 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-balance">Attention</h1>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="rounded-md border border-border bg-surface px-3 py-1.5 font-mono text-[11.5px] text-ink-dim hover:border-accent hover:text-ink disabled:opacity-50"
        >
          {refreshing ? "Checking…" : "↻ Re-check now"}
        </button>
      </div>
      <p className="mb-5 text-[13px] text-ink-dim">
        Everything that needs you, across every connection. ✨ items were detected by Sentinel — the reason shown is a
        fact, not a guess. 📌 items are reminders you created.
      </p>

      <form onSubmit={addReminder} className="mb-5 flex gap-2">
        <input
          value={newTitle}
          onChange={(e) => setNewTitle(e.target.value)}
          placeholder="Add a reminder — e.g. Follow up with the design team"
          className="flex-1 rounded-md border border-border bg-surface px-3.5 py-2 text-[13px] outline-none focus:border-accent"
        />
        <input
          type="datetime-local"
          value={newDue}
          onChange={(e) => setNewDue(e.target.value)}
          aria-label="Due (optional)"
          className="rounded-md border border-border bg-surface px-2.5 py-2 text-[12px] text-ink-dim outline-none focus:border-accent"
        />
        <button type="submit" disabled={!newTitle.trim()} className="rounded-md bg-accent px-3.5 py-2 font-mono text-[11.5px] font-bold text-ground disabled:opacity-50">
          Add
        </button>
      </form>

      <div className="mb-5 flex flex-wrap gap-1.5">
        {STATE_FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setStateFilter(f.key)}
            className={`rounded-full border px-3 py-1.5 font-mono text-[11.5px] transition-colors ${
              stateFilter === f.key ? "border-accent bg-accent/15 text-accent-text" : "border-border text-ink-faint hover:text-ink"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && <p className="mb-4 text-[12.5px] text-crit">{error}</p>}

      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 flex-1">
          {loading ? (
            <div className="text-ink-dim">Loading&hellip;</div>
          ) : items.length === 0 ? (
            <div className="rounded-md border border-dashed border-border p-8 text-center text-[13px] text-ink-faint">
              {stateFilter === "new" ? "Nothing needs your attention. ✨" : `No ${stateFilter} items.`}
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {items.map((item) => (
                <div key={item.id} className={`rounded-md border bg-surface p-3.5 ${askItem?.id === item.id ? "border-accent" : "border-border"}`}>
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 flex-none text-[17px]">{attentionIcon(item)}</span>
                    <div className="min-w-0 flex-1">
                      <div className={`text-[13.5px] font-semibold ${item.state === "done" ? "text-ink-faint line-through" : "text-ink"}`}>
                        {item.title}
                      </div>
                      <div className="mt-0.5 text-[11.5px] text-ink-faint">
                        {item.why}
                        {item.origin === "detected" ? " · ✨ AI-detected" : " · 📌 manual"}
                        {item.due_at && ` · due ${new Date(item.due_at).toLocaleString()}`}
                        {item.state === "snoozed" && item.snoozed_until && ` · snoozed until ${new Date(item.snoozed_until).toLocaleString()}`}
                      </div>
                    </div>
                  </div>
                  <div className="mt-2.5 flex flex-wrap items-center gap-3 pl-8 font-mono text-[10.5px]">
                    {item.state === "new" && (
                      <>
                        <button onClick={() => setState(item, "done")} className="text-ink-faint underline underline-offset-2 hover:text-good">
                          Mark done
                        </button>
                        <span className="relative">
                          <button
                            onClick={() => setSnoozeMenuFor(snoozeMenuFor === item.id ? null : item.id)}
                            className="text-ink-faint underline underline-offset-2 hover:text-watch"
                          >
                            Snooze &#9662;
                          </button>
                          {snoozeMenuFor === item.id && (
                            <span className="absolute left-0 top-5 z-10 flex flex-col rounded-md border border-border bg-surface shadow-lg">
                              {SNOOZE_OPTIONS.map((o) => (
                                <button
                                  key={o.label}
                                  onClick={() => setState(item, "snoozed", o.hours)}
                                  className="px-3 py-1.5 text-left text-[11px] text-ink-dim hover:bg-surface-2 hover:text-ink"
                                >
                                  {o.label}
                                </button>
                              ))}
                            </span>
                          )}
                        </span>
                        <button onClick={() => setState(item, "dismissed")} className="text-ink-faint underline underline-offset-2 hover:text-crit">
                          Dismiss
                        </button>
                        <button
                          onClick={() => setAskItem(askItem?.id === item.id ? null : item)}
                          className={`underline underline-offset-2 ${askItem?.id === item.id ? "text-accent-text" : "text-ink-faint hover:text-ink"}`}
                        >
                          Ask Sentinel ✨
                        </button>
                      </>
                    )}
                    {(item.state === "snoozed" || item.state === "dismissed" || item.state === "done") && (
                      <button onClick={() => setState(item, "new")} className="text-ink-faint underline underline-offset-2 hover:text-ink">
                        Reopen
                      </button>
                    )}
                    <EvidenceLink item={item} className="font-semibold text-accent-text hover:underline" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {askItem && (
          <div className="w-full flex-none lg:sticky lg:top-6 lg:w-[380px]">
            <div className="rounded-md border border-border bg-surface">
              <div className="flex items-center justify-between border-b border-border p-3.5">
                <div className="min-w-0">
                  <div className="text-[11px] text-ink-faint">Investigating</div>
                  <div className="truncate text-[13px] font-semibold text-ink">{askItem.title}</div>
                </div>
                <button onClick={() => setAskItem(null)} aria-label="Close" className="ml-2 flex-none rounded-md px-2 py-1 text-[13px] text-ink-faint hover:bg-surface-2 hover:text-ink">
                  &times;
                </button>
              </div>
              <GoogleAICommand
                contextPrefix={`Regarding this attention item: "${askItem.title}" (${askItem.why}).`}
                placeholder="Why does this matter? What should I do?"
                helpText={<>Sentinel will investigate this item across your connected services and can help you act on it.</>}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
