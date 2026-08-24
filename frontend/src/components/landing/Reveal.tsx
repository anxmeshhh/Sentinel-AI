import { useEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "../ui/cn";

/**
 * Scroll-triggered reveal, built on IntersectionObserver.
 *
 * No animation library: the whole landing page animates on transform and
 * opacity only, which the compositor handles without touching layout, so it
 * stays at 60fps on a phone. Adding a dependency to move two properties would
 * have been the expensive way to do less.
 *
 * Reveals fire ONCE. A section that re-animates every time it scrolls back
 * into view reads as a page that cannot settle, and the effect is meant to
 * direct attention on first read rather than perform continuously.
 */
export function useRevealed<T extends HTMLElement>(options?: { threshold?: number; rootMargin?: string }) {
  const ref = useRef<T>(null);
  const [revealed, setRevealed] = useState(() => prefersReducedMotion());

  useEffect(() => {
    // Reduced motion: show everything immediately and never observe. The
    // content is the point; the movement is decoration on top of it.
    if (prefersReducedMotion()) {
      setRevealed(true);
      return;
    }
    const node = ref.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setRevealed(true);
          observer.disconnect();
        }
      },
      { threshold: options?.threshold ?? 0.15, rootMargin: options?.rootMargin ?? "0px 0px -10% 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [options?.threshold, options?.rootMargin]);

  return { ref, revealed };
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * One element that fades and rises into place.
 *
 * `delay` staggers siblings. Kept small on purpose - a long stagger makes a
 * reader wait for the page instead of the page keeping up with the reader.
 */
export function Reveal({
  children,
  delay = 0,
  className,
  as: Tag = "div",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
  as?: "div" | "section" | "li" | "span" | "p";
}) {
  const { ref, revealed } = useRevealed<HTMLDivElement>();

  return (
    <Tag
      ref={ref as never}
      className={cn("lp-reveal", revealed && "lp-in", className)}
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
    >
      {children}
    </Tag>
  );
}
