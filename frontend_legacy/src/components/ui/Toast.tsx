import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { Icon } from "./Icon";
import { cn } from "./cn";

/**
 * The one transient-notification surface.
 *
 * Replaces the raw `alert()` calls that survived into a few admin actions -
 * a browser alert is unstyleable, blocks the whole page, and reads as a
 * different application than everything around it. A toast confirms or
 * reports without stealing focus, and matches the rest of the system.
 */

type ToastTone = "info" | "success" | "error";
interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

interface ToastApi {
  toast: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

let counter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const toast = useCallback((message: string, tone: ToastTone = "info") => {
    const id = ++counter;
    setItems((t) => [...t, { id, message, tone }]);
    setTimeout(() => setItems((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2">
        {items.map((item) => (
          <ToastCard key={item.id} item={item} onDismiss={() => setItems((t) => t.filter((x) => x.id !== item.id))} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

const TONE: Record<ToastTone, { border: string; icon: "check" | "alert" | "arrowRight"; iconColor: string }> = {
  success: { border: "border-good/40", icon: "check", iconColor: "text-good" },
  error: { border: "border-crit/40", icon: "alert", iconColor: "text-crit" },
  info: { border: "border-border-strong", icon: "arrowRight", iconColor: "text-ink-faint" },
};

function ToastCard({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const raf = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(raf);
  }, []);
  const tone = TONE[item.tone];
  return (
    <div
      className={cn(
        "pointer-events-auto flex items-start gap-2.5 rounded-md border bg-surface-2 px-3.5 py-2.5 shadow-overlay transition-all duration-200 ease-out",
        tone.border,
        visible ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0",
      )}
      role="status"
    >
      <Icon name={tone.icon} size={15} className={cn("mt-0.5", tone.iconColor)} />
      <span className="min-w-0 flex-1 text-caption text-ink-dim">{item.message}</span>
      <button onClick={onDismiss} aria-label="Dismiss" className="flex-none text-ink-faint transition-colors hover:text-ink">
        <Icon name="close" size={13} />
      </button>
    </div>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  // A no-op fallback rather than a throw: a stray toast call must never
  // crash a page just because it rendered outside the provider in a test.
  return ctx ?? { toast: () => undefined };
}
