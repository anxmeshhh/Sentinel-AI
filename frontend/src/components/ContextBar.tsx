import type { ContextIdentity } from "./context";
import { contextClasses } from "./context";
import { cn } from "./ui";

/**
 * The persistent "where am I, and what may Sentinel use here" strip.
 *
 * Sits directly above every AI input, so the answer is visible *before* a
 * message is sent rather than discovered afterwards. This exists because a
 * real user asked a work connection about private data — the two screens
 * looked identical and nothing stated the active context.
 *
 * Icon + word + name carry the meaning; the tone only reinforces it.
 */
export function ContextBar({ identity, className }: { identity: ContextIdentity; className?: string }) {
  const c = contextClasses(identity);
  return (
    <div className={cn("flex items-start gap-2.5 border-b px-3.5 py-2.5", c.border, c.bg, className)}>
      <span aria-hidden="true" className="mt-px flex-none text-caption">
        {identity.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className={cn("truncate text-caption font-semibold", c.text)}>{identity.title}</span>
          <span className="flex-none text-micro uppercase tracking-[0.12em] text-ink-faint">{identity.sharing}</span>
        </div>
        <p className="mt-0.5 text-micro leading-relaxed text-ink-faint">{identity.scopeNote}</p>
      </div>
    </div>
  );
}

/** The compact form: a single inline badge for headers and lists, where a
 *  full explanatory strip would be too heavy. */
export function ContextBadge({ identity, className }: { identity: ContextIdentity; className?: string }) {
  const c = contextClasses(identity);
  return (
    <span
      className={cn(
        "inline-flex flex-none items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-micro font-medium",
        c.border,
        c.bg,
        c.text,
        className,
      )}
    >
      <span aria-hidden="true">{identity.icon}</span>
      <span className="truncate">{identity.title}</span>
      <span className="text-ink-faint">·</span>
      <span className="uppercase tracking-[0.1em] text-ink-faint">{identity.sharing}</span>
    </span>
  );
}
