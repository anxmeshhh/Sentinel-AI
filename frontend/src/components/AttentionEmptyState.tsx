import { Link } from "react-router-dom";

import type { AttentionContext } from "../api/types";

/** An empty attention feed has three unrelated causes, and each one asks
 * something different of the user. Collapsing them into one blank message
 * reads as "broken" - the single impression an attention product cannot
 * afford, because the user can't tell whether it found nothing or failed. */
export function AttentionEmptyState({ context, filter }: { context: AttentionContext | null; filter: string }) {
  if (filter !== "new") {
    return <Shell>No {filter} items.</Shell>;
  }

  if (!context) return <Shell>Nothing needs your attention right now.</Shell>;

  // 1. Nothing connected - the user has to act before anything can appear.
  if (context.connection_count === 0) {
    return (
      <Shell>
        <p className="mb-2 text-ink-dim">Nothing is connected to this workspace yet.</p>
        <p className="mb-3 text-small">Sentinel needs a connection before it can find anything that matters.</p>
        <Link to="/connections/google" className="text-small font-semibold text-accent-text hover:underline">
          Connect Google &rarr;
        </Link>
      </Shell>
    );
  }

  // 2. Connected but no data yet. Covers both "nothing has synced" and
  //    "something synced but brought back nothing" - in either case
  //    claiming we checked everything would be false, since there was
  //    nothing to check.
  if (context.synced_connection_count === 0 || context.signals_seen === 0) {
    return (
      <Shell>
        <p className="mb-2 text-ink-dim">Still syncing your connections.</p>
        <p className="text-small">This usually takes under a minute. Re-check in a moment.</p>
      </Shell>
    );
  }

  // 3. Synced and genuinely clear - show the work so "nothing" is credible.
  return (
    <Shell>
      <p className="mb-2 text-lead text-ink">Nothing needs your attention. ✨</p>
      <p className="text-small">
        Checked {context.signals_seen.toLocaleString()} item{context.signals_seen === 1 ? "" : "s"}
        {context.filtered_as_noise > 0 && (
          <>
            {" "}— {context.filtered_as_noise} were newsletters or automated senders, so they were left out
          </>
        )}
        .
      </p>
      {context.last_synced_at && (
        <p className="mt-2 text-caption text-ink-faint">Last checked {new Date(context.last_synced_at).toLocaleString()}</p>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-border px-6 py-16 text-center text-body text-ink-dim">{children}</div>
  );
}
