import { useRef, useState } from "react";

import { api } from "../api/client";
import { BackNav } from "../components/BackNav";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export function AssistantPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  async function send() {
    const text = input.trim();
    if (!text || sending) return;

    const next: Message[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setSending(true);

    try {
      const { reply } = await api.post<{ reply: string }>("/assistant/chat", {
        message: text,
        history: next,
      });
      setMessages([...next, { role: "assistant", content: reply }]);
    } catch (e) {
      setMessages([
        ...next,
        { role: "assistant", content: e instanceof Error ? `Error: ${e.message}` : "Something went wrong." },
      ]);
    } finally {
      setSending(false);
      requestAnimationFrame(() => listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" }));
    }
  }

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-2xl flex-col md:h-[calc(100dvh-6rem)] md:min-h-0">
      <BackNav back={{ to: "/", label: "Dashboard" }} />
      <div className="mb-8">
        <h1 className="mb-1.5 text-xl font-semibold text-balance">AI Assistant</h1>
        <p className="text-[13px] leading-relaxed text-ink-dim">
          Ask about your own workspace. Answers are grounded only in your latest brief and
          findings — if something isn't in there yet, it'll say so.
        </p>
      </div>

      <div ref={listRef} className="flex-1 space-y-6 overflow-y-auto pb-6">
        {messages.length === 0 && (
          <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center text-[13px] text-ink-faint">
            No messages yet. Try: "What's the biggest risk right now?"
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={`max-w-[85%] rounded-lg px-4 py-3 text-[13.5px] leading-relaxed ${
                m.role === "user" ? "bg-accent/15 text-ink" : "bg-surface text-ink-dim"
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}
        {sending && <div className="text-[12.5px] text-ink-faint">Thinking&hellip;</div>}
      </div>

      <div className="flex gap-2.5 border-t border-border pt-5">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="Ask a question about your workspace…"
          className="flex-1 rounded-lg border border-border bg-surface px-4 py-3 text-[13.5px] outline-none focus:border-accent"
        />
        <button
          onClick={send}
          disabled={sending || !input.trim()}
          className="rounded-lg bg-accent px-5 py-3 text-[13.5px] font-bold text-ground disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}
