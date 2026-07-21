import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { cn } from "./cn";

export interface TabItem {
  to: string;
  label: ReactNode;
  /** Rendered after the label - a count, a warning dot, a "soon" marker. */
  trailing?: ReactNode;
  end?: boolean;
}

/** Route-driven tabs. Each tab is a destination, so only the selected
 *  module ever mounts and fetches - the channel modules depend on that.
 *
 *  Scrolls horizontally on narrow screens rather than wrapping to three
 *  rows, which would push the content itself below the fold. */
export function Tabs({ items, className }: { items: TabItem[]; className?: string }) {
  return (
    <nav className={cn("scroll-x mb-7 flex gap-1 border-b border-rule-strong pb-2.5 sm:mb-8", className)}>
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            cn(
              "flex flex-none items-center gap-2 whitespace-nowrap rounded-md px-3.5 py-2 text-small transition-colors duration-200",
              isActive ? "bg-surface-2 font-semibold text-ink" : "text-ink-dim hover:bg-surface/70 hover:text-ink",
            )
          }
        >
          {item.label}
          {item.trailing}
        </NavLink>
      ))}
    </nav>
  );
}
