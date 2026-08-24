import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Agentic } from "../components/landing/Agentic";
import { AssistantDemo } from "../components/landing/AssistantDemo";
import { Hero } from "../components/landing/Hero";
import { HowItThinks } from "../components/landing/HowItThinks";
import { Intelligence } from "../components/landing/Intelligence";
import { MemoryGoals } from "../components/landing/MemoryGoals";
import { FinalCta, Principles } from "../components/landing/Principles";
import { Problem } from "../components/landing/Problem";
import { ProductShowcase } from "../components/landing/ProductShowcase";
import { Scope } from "../components/landing/Scope";
import { Hairline } from "../components/landing/primitives";
import { cn } from "../components/ui/cn";

/**
 * The Sentinel landing page.
 *
 * One continuous argument rather than a feature list: work is scattered ->
 * here is how the pipeline reads it -> here is what it surfaces -> it can
 * also act -> here is why that is safe -> here is the real product.
 *
 * Deliberately outside AppShell. There is no sidebar, no workspace and no
 * authenticated state here, and wrapping it in the application chrome would
 * both leak product UI to a stranger and imply they are already inside it.
 *
 * No animation dependency: every motion on this page is a CSS transition on
 * transform or opacity, triggered by IntersectionObserver. Adding a library
 * to move two composited properties would have been weight for nothing.
 */
export function LandingPage() {
  return (
    <div className="min-h-screen bg-ground text-ink antialiased">
      <TopBar />
      <main>
        <Hero />
        <Hairline />
        <Problem />
        <Hairline />
        <HowItThinks />
        <Hairline />
        <Intelligence />
        <Hairline />
        <Agentic />
        <Hairline />
        <Scope />
        <Hairline />
        <MemoryGoals />
        <Hairline />
        <AssistantDemo />
        <Hairline />
        <Principles />
        <Hairline />
        <ProductShowcase />
        <FinalCta />
      </main>
      <Footer />
    </div>
  );
}

/**
 * Transparent over the hero, and only gains its border once the page has
 * moved - so the first screen stays uninterrupted and the bar still has an
 * edge to sit on when content scrolls under it.
 */
function TopBar() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    // Passive: this listener must never be able to delay a scroll.
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div
      className={cn(
        "sticky top-0 z-50 transition-colors duration-300",
        scrolled ? "border-b border-border bg-ground/85 backdrop-blur-md" : "border-b border-transparent",
      )}
    >
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-5 py-4 sm:px-8">
        <Link to="/welcome" className="flex items-center gap-2.5" aria-label="Sentinel home">
          <span
            className="flex h-6 w-6 flex-none items-center justify-center rounded-lg bg-accent/15 ring-1 ring-inset ring-accent/40"
            aria-hidden="true"
          >
            <span className="h-2 w-2 rounded-full bg-accent" />
          </span>
          <span className="text-small font-semibold tracking-tight text-ink">Sentinel</span>
        </Link>

        <nav className="hidden items-center gap-7 md:flex" aria-label="Sections">
          {[
            ["How it works", "#how"],
            ["Intelligence", "#intelligence"],
            ["Privacy", "#scope"],
            ["Product", "#product"],
          ].map(([label, href]) => (
            <a
              key={href}
              href={href}
              className="text-caption text-ink-dim transition-colors duration-200 hover:text-ink"
            >
              {label}
            </a>
          ))}
        </nav>

        <Link
          to="/login"
          className="inline-flex items-center justify-center rounded-md border border-border px-3.5 py-1.5 text-caption font-medium text-ink-dim transition-colors duration-200 hover:border-border-strong hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Sign in
        </Link>
      </div>
    </div>
  );
}

function Footer() {
  return (
    <footer className="border-t border-rule">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-5 py-10 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <p className="text-micro text-ink-faint">
          Sentinel — operations intelligence over the tools you already use.
        </p>
        <div className="flex items-center gap-6">
          <a
            href="https://github.com/anxmeshhh/Sentinel-AI"
            target="_blank"
            rel="noreferrer"
            className="text-micro text-ink-faint transition-colors duration-200 hover:text-ink-dim"
          >
            GitHub
          </a>
          <Link
            to="/login"
            className="text-micro text-ink-faint transition-colors duration-200 hover:text-ink-dim"
          >
            Sign in
          </Link>
        </div>
      </div>
    </footer>
  );
}
