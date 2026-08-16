import { useState } from "react";
import { ctxColor, type ContextKind } from "@/lib/sentinel-data";
import { ActionButton } from "./action-button";

interface Msg {
  from: "you" | "sentinel";
  text: string;
  cite?: string;
  action?: boolean;
}

export function Assistant({
  contextLabel,
  contextKind = "personal",
  placeholder = "Ask about your work…",
  prompts = [],
}: {
  contextLabel: string;
  contextKind?: ContextKind;
  placeholder?: string;
  prompts?: string[];
}) {
  const [thread, setThread] = useState<Msg[]>([]);
  const [value, setValue] = useState("");
  const [thinking, setThinking] = useState(false);

  function send(text: string) {
    if (!text.trim()) return;
    setThread((t) => [...t, { from: "you", text }]);
    setValue("");
    setThinking(true);
    setTimeout(() => {
      setThinking(false);
      setThread((t) => [
        ...t,
        {
          from: "sentinel",
          text: "The deployment review starts at 15:00 and has no agenda, and the rollback task for heartbeat-harmony is four days overdue. Preparing the agenda first is the shorter path.",
          cite: "Based on 2 findings about heartbeat-harmony",
          action: true,
        },
      ]);
    }, 900);
  }

  return (
    <section className="flex min-h-[380px] flex-col rounded-[6px] border border-border bg-surface p-4">
      <header className="t-micro flex items-center gap-2 text-ink-faint">
        <span
          aria-hidden
          className="inline-block size-1.5 rounded-full"
          style={{ background: ctxColor[contextKind] }}
        />
        {contextLabel}
      </header>

      <div className="mt-3 flex-1 space-y-3">
        {thread.length === 0 && prompts.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {prompts.slice(0, 3).map((p) => (
              <button
                key={p}
                onClick={() => send(p)}
                className="focus-ring t-caption rounded-[3px] border border-border px-2 py-1 text-ink-faint transition-colors duration-150 hover:border-border-strong hover:text-ink"
              >
                {p}
              </button>
            ))}
          </div>
        )}

        {thread.map((m, i) => (
          <div key={i} className={m.from === "you" ? "flex justify-end" : ""}>
            <div className={m.from === "you" ? "max-w-[85%]" : ""}>
              <p
                className={
                  m.from === "you"
                    ? "t-small rounded-[4px] bg-surface-3 px-3 py-2 text-ink"
                    : "t-small text-ink-dim"
                }
              >
                {m.text}
              </p>
              {m.cite && <p className="t-micro mt-1 text-ink-faint">{m.cite}</p>}
              {m.action && (
                <div className="mt-2">
                  <ActionButton
                    spec={{
                      label: "Create task",
                      preview: 'Create "Draft the deployment review agenda" in Microsoft To Do',
                      detail: "Creates a real task due today. Nobody is notified.",
                      verification:
                        "Microsoft To Do has 'Draft the deployment review agenda' due today.",
                      undoable: true,
                    }}
                  />
                </div>
              )}
            </div>
          </div>
        ))}

        {thinking && <p className="t-caption text-ink-faint">Thinking…</p>}
      </div>

      <form
        className="mt-3"
        onSubmit={(e) => {
          e.preventDefault();
          send(value);
        }}
      >
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          className="focus-ring t-small w-full rounded-[4px] border border-border bg-surface-2 px-3 py-2 text-ink placeholder:text-ink-faint"
        />
      </form>
    </section>
  );
}
