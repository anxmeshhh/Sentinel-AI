import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import {
  ctxColor,
  findings,
  serviceByKey,
  severityColor,
  situations,
} from "@/lib/sentinel-data";
import { Dot, SectionLabel } from "./primitives";

interface Item {
  group: string;
  label: string;
  hint?: string | undefined;
  color?: string | undefined;
  to: string;
}

export function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const navigate = useNavigate();

  const items = useMemo<Item[]>(() => {
    const q = query.trim().toLowerCase();
    const all: Item[] = [
      ...situations.map((s) => ({
        group: "Situations",
        label: s.entity,
        hint: `${s.findingIds.length} findings`,
        color: severityColor[s.severity],
        to: `/situations/${s.id}`,
      })),
      ...findings.map((f) => ({
        group: "Findings",
        label: f.title,
        hint: serviceByKey(f.service)?.name,
        color: severityColor[f.severity],
        to: `/findings/${f.id}`,
      })),
      { group: "Go to", label: "Connections", to: "/connections" },
      { group: "Go to", label: "What Sentinel remembers", to: "/memory" },
      { group: "Go to", label: "History", to: "/history" },
      { group: "Go to", label: "Settings", to: "/settings" },
      { group: "Actions", label: "Schedule a meeting", to: "/workspace/zoom" },
      { group: "Actions", label: "Create a task", to: "/workspace/microsoft_todo" },
    ];
    return q ? all.filter((i) => i.label.toLowerCase().includes(q)) : all.slice(0, 10);
  }, [query]);

  useEffect(() => setActive(0), [query]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((a) => Math.min(a + 1, items.length - 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((a) => Math.max(a - 1, 0));
      }
      if (e.key === "Enter" && items[active]) {
        onClose();
        navigate({ to: items[active]!.to });
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, items, active, navigate, onClose]);

  if (!open) return null;

  let lastGroup = "";

  return (
    <div
      className="fixed inset-0 z-50 flex justify-center px-4 pt-[15vh]"
      style={{ background: "rgba(0,0,0,0.72)" }}
      onClick={onClose}
    >
      <div
        className="overlay-shadow anim-in h-fit w-full max-w-[640px] rounded-[8px] border border-border bg-surface-2"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
          <Dot color={ctxColor.personal} />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search or type a command…"
            className="focus-ring t-small w-full bg-transparent text-ink placeholder:text-ink-faint"
          />
          <span className="t-micro text-ink-faint">esc</span>
        </div>

        <div className="max-h-[52vh] overflow-y-auto p-2">
          {items.length === 0 ? (
            <p className="t-caption px-2 py-6 text-ink-faint">
              Nothing matched “{query}”. Try a person, a repository, or a subject line.
            </p>
          ) : (
            items.map((i, idx) => {
              const header = i.group !== lastGroup ? i.group : null;
              lastGroup = i.group;
              return (
                <div key={i.to + i.label}>
                  {header && <SectionLabel className="px-2 pb-1 pt-3">{header}</SectionLabel>}
                  <button
                    onMouseEnter={() => setActive(idx)}
                    onClick={() => {
                      onClose();
                      navigate({ to: i.to });
                    }}
                    className="flex w-full items-center gap-2 rounded-[3px] px-2 py-1.5 text-left"
                    style={idx === active ? { background: "var(--surface-3)" } : undefined}
                  >
                    {i.color ? <Dot color={i.color} /> : <span className="t-micro text-ink-faint">→</span>}
                    <span className="t-small flex-1 truncate text-ink">{i.label}</span>
                    {i.hint && <span className="t-micro text-ink-faint">{i.hint}</span>}
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
