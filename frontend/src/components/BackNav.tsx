import { Link } from "react-router-dom";

interface Crumb {
  label: string;
  to?: string;
}

/** Consistent, prominent "← Back" (+ optional "Dashboard" + breadcrumb trail)
 * for every nested page - explicit named routes rather than history.back(),
 * since "the previous logical page" (e.g. Gmail → Google Workspace) should
 * always be the same place regardless of how the user actually arrived. */
export function BackNav({ back, crumbs }: { back: { to: string; label: string }; crumbs?: Crumb[] }) {
  return (
    <div className="mb-5">
      <div className="flex flex-wrap items-center gap-2">
        <Link
          to={back.to}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface shadow-card px-3 py-1.5 text-small font-semibold text-ink-dim transition-colors hover:border-accent hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <span aria-hidden="true">&larr;</span> {back.label}
        </Link>
        {back.to !== "/" && (
          <Link
            to="/"
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-small text-ink-faint transition-colors hover:border-accent hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Dashboard
          </Link>
        )}
      </div>
      {crumbs && crumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="mt-2 flex flex-wrap items-center gap-1 text-caption text-ink-faint">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span aria-hidden="true">&rsaquo;</span>}
              {c.to ? (
                <Link to={c.to} className="underline-offset-2 hover:text-ink hover:underline">
                  {c.label}
                </Link>
              ) : (
                <span className="text-ink-dim">{c.label}</span>
              )}
            </span>
          ))}
        </nav>
      )}
    </div>
  );
}
