import { Link } from "react-router-dom";

import type { ChannelPath } from "../api/types";

/**
 * Workspace / Class / Group / #Channel.
 *
 * Every segment is rendered even though only the channel is currently a
 * navigable page - knowing *where you are* is the point, and greying out
 * the levels that don't have their own screen yet is more honest than
 * hiding them and leaving the trail incomplete.
 */
export function ChannelBreadcrumb({ path }: { path: ChannelPath }) {
  return (
    <nav aria-label="Breadcrumb" className="scroll-x mb-4 flex items-center gap-2 whitespace-nowrap pb-1 text-caption text-ink-faint sm:flex-wrap sm:whitespace-normal">
      <Link to="/" className="hover:text-ink hover:underline underline-offset-2">
        {path.workspace_name.trim()}
      </Link>
      <Separator />
      <span className="text-ink-dim">{path.class_name}</span>
      <Separator />
      <span className="text-ink-dim">{path.group_name}</span>
      <Separator />
      <span className="font-semibold text-ink">#{path.channel_name}</span>
    </nav>
  );
}

function Separator() {
  return <span aria-hidden="true">/</span>;
}
