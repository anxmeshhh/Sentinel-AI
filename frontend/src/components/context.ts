import type { Workspace } from "../context/WorkspaceContext";

/**
 * Which "world" the user is currently in — the one place that answer is
 * derived, so the rail, the tree, page headers and every AI panel can never
 * disagree about it.
 *
 * The problem this exists to solve is concrete: Personal and Organization
 * screens were near-identical, and a user asked a work connection about
 * private data because nothing on screen said which context was active.
 *
 * Three rules keep it from turning Sentinel into three different products:
 *  - colour is always paired with an icon AND a word, so meaning survives
 *    greyscale, colour blindness and small type;
 *  - the tone appears only in glows, hairline borders and badges — never as
 *    a page fill;
 *  - a Channel does not get a tone of its own. It inherits its Class's,
 *    because "which world am I in" is answered by the parent, and a
 *    per-channel colour would be noise rather than signal.
 */

export type ContextKind = "personal" | "organization" | "class";

export interface ContextIdentity {
  kind: ContextKind;
  /** Tailwind colour token name, e.g. "ctx-personal". */
  tone: string;
  icon: string;
  /** Short name of the world: "Personal", "Acme Corporation", "Development". */
  title: string;
  /** PRIVATE / SHARED — the single most load-bearing word on screen. */
  sharing: "Private" | "Shared";
  /** What Sentinel may use here, in one plain sentence. */
  scopeNote: string;
}

const TONE: Record<ContextKind, string> = {
  personal: "ctx-personal",
  organization: "ctx-org",
  class: "ctx-class",
};

const ICON: Record<ContextKind, string> = {
  personal: "🔒",
  organization: "👥",
  class: "🎓",
};

/** The workspace-level identity: Personal vs an Organization. */
export function workspaceContext(workspace: Workspace | null): ContextIdentity {
  if (workspace?.kind === "personal") {
    return {
      kind: "personal",
      tone: TONE.personal,
      icon: ICON.personal,
      title: "Personal",
      sharing: "Private",
      scopeNote: "Using your private connections. Nothing here is shared with any workspace or channel.",
    };
  }
  const name = workspace?.name?.trim() || "Workspace";
  return {
    kind: "organization",
    tone: TONE.organization,
    icon: ICON.organization,
    title: name,
    sharing: "Shared",
    scopeNote: `Using connections authorized for ${name}, subject to your role and permissions.`,
  };
}

/**
 * Inside a channel the operative world is its Class — that is the shared
 * boundary the connections actually belong to — so the channel shows the
 * class tone and names the full path.
 */
export function channelContext(className: string, channelName: string, workspaceName?: string): ContextIdentity {
  return {
    kind: "class",
    tone: TONE.class,
    icon: ICON.class,
    title: `${className} → #${channelName}`,
    sharing: "Shared",
    scopeNote: `Using only the connections authorized for #${channelName}${
      workspaceName ? ` in ${workspaceName}` : ""
    }. Never the rest of the workspace.`,
  };
}

/**
 * Tailwind classes for the subtle treatments, defined once.
 *
 * Written out literally per context rather than interpolated (`text-${tone}`)
 * on purpose: Tailwind generates CSS by scanning source for complete class
 * strings, so a constructed name is purged from the build and the style
 * silently doesn't exist. These have to stay whole to survive.
 */
const CLASSES: Record<ContextKind, { text: string; border: string; bg: string; solid: string }> = {
  personal: {
    text: "text-ctx-personal",
    border: "border-ctx-personal/35",
    bg: "bg-ctx-personal/[0.07]",
    solid: "bg-ctx-personal",
  },
  organization: {
    text: "text-ctx-org",
    border: "border-ctx-org/35",
    bg: "bg-ctx-org/[0.07]",
    solid: "bg-ctx-org",
  },
  class: {
    text: "text-ctx-class",
    border: "border-ctx-class/35",
    bg: "bg-ctx-class/[0.07]",
    solid: "bg-ctx-class",
  },
};

export function contextClasses(identity: ContextIdentity) {
  return CLASSES[identity.kind];
}
