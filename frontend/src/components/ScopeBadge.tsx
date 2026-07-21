import type { Workspace } from "../context/WorkspaceContext";

/** One vocabulary for "who can use this", used everywhere a connection or
 * an AI context appears. Consistency is the point: a user should learn
 * these three symbols once and then recognise them instantly on any screen.
 *
 * Never colour-only - each state carries an icon AND a word, so the meaning
 * survives colour blindness, greyscale, and small type.
 */
export type Scope = "personal" | "workspace" | "channel";

export function scopeOf(workspace: Workspace | null): Scope {
  return workspace?.kind === "personal" ? "personal" : "workspace";
}

const STYLES: Record<Scope, string> = {
  personal: "border-good/40 bg-good/10 text-good",
  workspace: "border-accent/40 bg-accent/10 text-accent-text",
  channel: "border-border bg-surface-2 text-ink-dim",
};

const ICONS: Record<Scope, string> = { personal: "🔒", workspace: "👥", channel: "#" };

export function scopeLabel(scope: Scope, workspaceName?: string): string {
  if (scope === "personal") return "Private to you";
  if (scope === "channel") return "Channel-scoped";
  return workspaceName ? `Shared with ${workspaceName}` : "Shared workspace";
}

export function scopeExplanation(scope: Scope, workspaceName?: string): string {
  if (scope === "personal") return "Only your personal Sentinel can use this connection. It is never shared with a workspace or channel.";
  if (scope === "channel") return "Sentinel can only use this inside this channel.";
  return `Available within ${workspaceName ?? "this workspace"} according to member and channel permissions.`;
}

export function ScopeBadge({ scope, workspaceName, className = "" }: { scope: Scope; workspaceName?: string; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-[3px] font-mono text-caption ${STYLES[scope]} ${className}`}
    >
      <span aria-hidden="true">{ICONS[scope]}</span>
      {scopeLabel(scope, workspaceName)}
    </span>
  );
}

/** The full "who can use this" statement - badge plus one plain sentence.
 * Used at the top of connection surfaces so the answer is visible without
 * opening settings or hovering anything. */
export function ScopeNotice({ scope, workspaceName }: { scope: Scope; workspaceName?: string }) {
  return (
    <div className="mb-5 rounded-lg border border-border bg-surface shadow-card p-3.5">
      <ScopeBadge scope={scope} workspaceName={workspaceName} />
      <p className="mt-2 text-small leading-relaxed text-ink-dim">{scopeExplanation(scope, workspaceName)}</p>
    </div>
  );
}
