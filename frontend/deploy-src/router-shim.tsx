import type { AnchorHTMLAttributes, ReactNode } from "react";

/**
 * A stand-in for react-router-dom, used only by the standalone landing build.
 *
 * The deployed folder is one static page, so there is no router and no
 * in-app destination for `to="/login"` to reach. Rather than ship a router
 * whose every route resolves to the same page - a Sign in button that
 * silently re-renders the page you are on reads as broken software, not as
 * a marketing site - this maps the two cases that actually exist:
 *
 *   /welcome, /       the page itself
 *   anything else     the repository, which is where a visitor can
 *                     currently go and see the real thing
 *
 * Aliased in vite.landing.config.ts. The application build is untouched and
 * still uses the real react-router-dom.
 */
const REPO_URL = "https://github.com/anxmeshhh/Sentinel-AI";

type Anchor = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">;

type LinkProps = Anchor & {
  to: string;
  replace?: boolean;
  state?: unknown;
  children?: ReactNode;
};

function resolve(to: string): { href: string; external: boolean } {
  if (to.startsWith("#") || to.startsWith("http")) {
    return { href: to, external: to.startsWith("http") };
  }
  if (to === "/" || to === "/welcome") return { href: "/", external: false };
  return { href: REPO_URL, external: true };
}

export function Link({ to, replace, state, children, ...rest }: LinkProps) {
  void replace;
  void state;
  const { href, external } = resolve(to);
  return (
    <a
      href={href}
      {...(external ? { target: "_blank", rel: "noreferrer" } : {})}
      {...rest}
    >
      {children}
    </a>
  );
}

/**
 * Only present because the design-system barrel re-exports Tabs, which
 * imports NavLink. Nothing on the landing page renders one.
 */
type NavLinkProps = Omit<LinkProps, "className" | "children"> & {
  className?: string | ((s: { isActive: boolean; isPending: boolean }) => string);
  children?: ReactNode | ((s: { isActive: boolean; isPending: boolean }) => ReactNode);
  end?: boolean;
};

export function NavLink({ className, children, end, ...rest }: NavLinkProps) {
  void end;
  const state = { isActive: false, isPending: false };
  return (
    <Link
      {...rest}
      className={typeof className === "function" ? className(state) : className}
    >
      {typeof children === "function" ? children(state) : children}
    </Link>
  );
}
