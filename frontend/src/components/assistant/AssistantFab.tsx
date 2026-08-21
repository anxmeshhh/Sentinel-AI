import { Link } from "react-router-dom";

import { Icon } from "../ui";

/**
 * The way into the Assistant, from a page that no longer embeds it.
 *
 * Replaces the "large Ask Sentinel section" that used to sit inline on the
 * Attention page - a quiet bar, or a full composer once opened. That was a
 * second, page-local entry point into a capability the Assistant already
 * owns end to end (catch-up, triage, investigate, prepare, act). This is a
 * shortcut to the one real Assistant, not a second one: it navigates,
 * nothing here answers a question or holds conversation state.
 *
 * `position: fixed` anchors to the viewport regardless of the page's own
 * scrolling - the app shell's `overflow-y-auto` on `<main>` does not create
 * a new containing block, only `transform`/`filter`/`will-change` would.
 */
export function AssistantFab({ to = "/assistant" }: { to?: string }) {
  return (
    <Link
      to={to}
      aria-label="Open Sentinel Assistant"
      title="Ask Sentinel"
      className="fixed bottom-6 right-6 z-30 flex h-12 w-12 items-center justify-center rounded-full bg-accent text-white shadow-overlay transition-transform duration-200 hover:scale-105 hover:bg-accent-hover"
    >
      <Icon name="sparkle" size={20} />
    </Link>
  );
}
