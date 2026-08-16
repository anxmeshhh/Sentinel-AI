import { useEffect, useState } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import {
  contexts,
  ctxColor,
  findings,
  notifications,
  services,
  situations,
} from "@/lib/sentinel-data";
import { ButtonGhost, Dot, SectionLabel } from "./primitives";
import { CommandPalette } from "./command-palette";

const primaryNav = [
  { label: "Command", to: "/" },
  { label: "Situations", to: "/situations" },
  { label: "Findings", to: "/findings" },
] as const;

const tailNav = [
  { label: "Memory", to: "/memory" },
  { label: "History", to: "/history" },
] as const;

const systemNav = [
  { label: "Connections", to: "/connections" },
  { label: "Settings", to: "/settings" },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [contextId, setContextId] = useState("personal");
  const [ctxOpen, setCtxOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  const ctx = contexts.find((c) => c.id === contextId)!;
  const openCritical = findings.filter(
    (f) => f.status === "open" && f.severity === "critical",
  ).length;
  const openFindings = findings.filter((f) => f.status === "open").length;
  const unread = notifications.some((n) => n.unread);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="min-h-screen bg-ground">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b border-border bg-ground px-4">
        <Link to="/" className="t-small font-semibold tracking-tight text-ink">
          Sentinel
        </Link>

        <div className="relative">
          <button
            onClick={() => setCtxOpen((v) => !v)}
            className="focus-ring t-caption flex items-center gap-2 rounded-[3px] border border-border px-2.5 py-1 text-ink-dim hover:border-border-strong hover:text-ink"
          >
            <Dot color={ctxColor[ctx.kind]} />
            {ctx.name}
            <span className="t-micro text-ink-faint">▾</span>
          </button>
          {ctxOpen && (
            <div className="overlay-shadow anim-in absolute left-0 top-full z-40 mt-2 w-64 rounded-[6px] border border-border bg-surface-2 p-2">
              {(["personal", "org", "class"] as const).map((kind) => {
                const group = contexts.filter((c) => c.kind === kind);
                if (!group.length) return null;
                return (
                  <div key={kind} className="mb-2 last:mb-0">
                    <SectionLabel className="px-2 py-1">
                      {kind === "personal"
                        ? "Personal"
                        : kind === "org"
                          ? "Workspaces"
                          : "Channels"}
                    </SectionLabel>
                    {group.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => {
                          setContextId(c.id);
                          setCtxOpen(false);
                        }}
                        className="flex w-full items-center gap-2 rounded-[3px] px-2 py-1.5 text-left hover:bg-surface-3"
                      >
                        <Dot color={ctxColor[c.kind]} />
                        <span className="t-caption flex-1 text-ink">{c.name}</span>
                        <span className="t-micro text-ink-faint">{c.detail}</span>
                      </button>
                    ))}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex-1" />

        <button
          onClick={() => setPaletteOpen(true)}
          className="focus-ring t-caption hidden items-center gap-2 rounded-[3px] border border-border px-2.5 py-1 text-ink-faint hover:border-border-strong hover:text-ink sm:flex"
        >
          Search <span className="t-micro font-mono">⌘K</span>
        </button>

        <div className="relative">
          <button
            onClick={() => setBellOpen((v) => !v)}
            aria-label="Notifications"
            className="focus-ring t-caption relative rounded-[3px] px-2 py-1 text-ink-faint hover:text-ink"
          >
            Notifications
            {unread && (
              <span
                className="absolute right-0 top-1 size-1.5 rounded-full"
                style={{ background: "var(--brand)" }}
              />
            )}
          </button>
          {bellOpen && (
            <div className="overlay-shadow anim-in absolute right-0 top-full z-40 mt-2 max-h-[480px] w-[360px] overflow-y-auto rounded-[6px] border border-border bg-surface-2">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <SectionLabel>Notifications</SectionLabel>
                <ButtonGhost>Mark all read</ButtonGhost>
              </div>
              <ul className="divide-y divide-border">
                {notifications.map((n) => (
                  <li key={n.id}>
                    <Link
                      to={n.to}
                      onClick={() => setBellOpen(false)}
                      className="block px-3 py-2.5 hover:bg-surface-3"
                    >
                      <span className="t-caption block text-ink-dim">
                        {n.kind === "memory" ? "🧠 " : ""}
                        {n.text}
                      </span>
                      <span className="t-micro text-ink-faint">{n.when}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <span className="grid size-7 place-items-center rounded-full border border-border">
          <span className="t-micro text-ink-dim">A</span>
        </span>
      </header>

      <div className="flex">
        <nav className="sticky top-14 hidden h-[calc(100vh-56px)] w-60 shrink-0 overflow-y-auto border-r border-border bg-surface px-3 py-4 lg:block">
          <NavGroup items={primaryNav} pathname={pathname} counts={{ "/findings": openFindings }} critical={{ "/findings": openCritical }} situations={situations.length} />

          <div className="my-4 border-t border-rule" />
          <SectionLabel className="px-2 pb-1">Workspaces</SectionLabel>
          <ul>
            {services.map((s) => (
              <li key={s.key}>
                <Link
                  to="/workspace/$service"
                  params={{ service: s.key }}
                  className="t-caption block rounded-[8px] px-3 py-2 text-ink-dim transition-colors duration-150 hover:text-ink"
                  activeProps={{
                    style: {
                      background: "var(--surface-2)",
                      color: "var(--ink)",
                      borderLeft: "2px solid var(--brand)",
                    },
                  }}
                >
                  {s.name}
                </Link>
              </li>
            ))}
          </ul>

          <div className="my-4 border-t border-rule" />
          <NavGroup items={tailNav} pathname={pathname} />
          <div className="my-4 border-t border-rule" />
          <NavGroup items={systemNav} pathname={pathname} />
        </nav>

        <main
          className="min-w-0 flex-1 px-4 py-6 md:px-6"
          style={
            ctx.kind === "personal"
              ? { borderTop: `1px solid color-mix(in oklch, var(--ctx-personal) 40%, transparent)` }
              : undefined
          }
        >
          <div className="mx-auto max-w-[1200px]">{children}</div>
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}

function NavGroup({
  items,
  pathname,
  counts = {},
  critical = {},
  situations,
}: {
  items: readonly { label: string; to: string }[];
  pathname: string;
  counts?: Record<string, number>;
  critical?: Record<string, number>;
  situations?: number;
}) {
  return (
    <ul>
      {items.map((i) => {
        const active = i.to === "/" ? pathname === "/" : pathname.startsWith(i.to);
        const count =
          i.to === "/situations" ? situations : counts[i.to];
        const crit = critical[i.to];
        return (
          <li key={i.to}>
            <Link
              to={i.to}
              className="t-caption flex items-center justify-between rounded-[8px] px-3 py-2 text-ink-dim transition-colors duration-150 hover:text-ink"
              style={
                active
                  ? {
                      background: "var(--surface-2)",
                      color: "var(--ink)",
                      borderLeft: "2px solid var(--brand)",
                    }
                  : undefined
              }
            >
              {i.label}
              {count ? (
                <span
                  className="t-micro font-mono"
                  style={{ color: crit ? "var(--crit)" : "var(--ink-faint)" }}
                >
                  {crit ? crit : count}
                </span>
              ) : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
