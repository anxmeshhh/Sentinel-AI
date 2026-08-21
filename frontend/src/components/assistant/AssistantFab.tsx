import { Link } from "react-router-dom";

import { Icon } from "../ui";

/**
 * The one way into the one Assistant, from every page.
 *
 * Mounted exactly once, in App.tsx's AppShell, so it appears on every
 * authenticated route without each page wiring its own copy - a page that
 * imports this a second time is a mistake, not a feature. It replaces every
 * page-level "Ask Sentinel" bar and embedded chat panel that used to
 * duplicate the Assistant's job (Dashboard's composer, the generic
 * provider-wide assistant rail on Connections and provider workspaces,
 * Calendar's "Ask AI" tab): those surfaces answered the same questions this
 * button's destination already does, from a second, separate conversation
 * state each time. What survives elsewhere is only genuinely different in
 * kind - a per-record question tied to one specific finding or file, which
 * this button does not replace and was never meant to.
 *
 * This component itself holds no conversation state and calls no chat
 * endpoint. It navigates, nothing more; the Assistant page owns everything
 * about what happens after the click.
 *
 * `position: fixed` anchors to the viewport regardless of the page's own
 * scrolling - the app shell's `overflow-y-auto` on `<main>` does not create
 * a new containing block, only `transform`/`filter`/`will-change` would.
 * The bottom offset adds the device's safe-area inset on top of the usual
 * spacing, so it clears a phone's home-indicator strip; `max()` means a
 * device with no inset (most desktops) just gets the plain 1.5rem.
 */
export function AssistantFab({ to = "/assistant" }: { to?: string }) {
  return (
    <Link
      to={to}
      aria-label="Open Sentinel Assistant"
      title="Ask Sentinel"
      style={{ bottom: "max(1.5rem, calc(env(safe-area-inset-bottom, 0px) + 1rem))" }}
      className="fixed right-6 z-30 flex h-12 w-12 items-center justify-center rounded-full bg-accent text-white shadow-overlay transition-transform duration-200 hover:scale-105 hover:bg-accent-hover"
    >
      <Icon name="sparkle" size={20} />
    </Link>
  );
}
